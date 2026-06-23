"""SSE streaming endpoint for the ReAct (Reason+Act) chat loop.

Implements the core intelligence pipeline:
    User query → image analysis → memory recall → routing → ReAct loop
    → parallel tool execution → validation → debate → streaming response

Each step emits Server-Sent Events so the frontend can render reasoning
in real-time (thinking bubbles, tool cards, map overlays, etc.).

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time

import structlog
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.config import (
    AGENT_LABELS,
    CRITICAL_TOOLS,
    MAX_REACT_STEPS,
    MODEL_AIR,
    REACT_SYSTEM_PROMPT,
    TOOL_TO_SERVER,
    UPLOAD_IMG_DIR,
    _tool_cache,
)
from app.knowledge import CITY_COORDS
from app.dispatcher import handle_internal_tool
from app.pipeline import detect_pipeline, execute_pipeline
from app.llm import call_llm
from app.mcp_client import cached_mcp_call
from app.multimodal import analyze_image
from app.router import route
from app.store import MemoryStore
from app.tools.generator import (
    check_result_quality,
    delete_generated,
    exec_generated,
    generate_tool_with_retry,
)
from app.tracing import _log_evolution, new_trace
from app.utils import (
    compress_result,
    detect_ui_action,
    format_tool_summary,
    sse,
    stream_words,
    trim_context,
)
from app.validators import debate_validate, inject_commonsense, validate_physics, validate_result

__author__ = "jumpingbirds"
__email__ = "guodaochong@gmail.com"

logger = structlog.get_logger(__name__)
router = APIRouter()
_memory = MemoryStore()


def _parse_history(raw: str) -> list[dict]:
    """Deserialize conversation history from JSON string."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


async def _resolve_image_prefix(message: str) -> tuple[str, list[dict]]:
    """If the message starts with ``[img:...]``, run vision analysis and enrich the message.

    Returns ``(enriched_message, sse_events_to_emit)``.
    """
    if not message.startswith("[img:"):
        return message, []

    img_name = message[5:].strip().rstrip("]").strip()
    img_path = UPLOAD_IMG_DIR / img_name
    if not img_path.exists():
        return message, []

    img_b64 = base64.b64encode(img_path.read_bytes()).decode()
    analysis = await analyze_image(img_b64)
    events = [
        {"type": "thinking_start", "agent": "vision", "label": "🔍 图片分析"},
        {"type": "thinking", "agent": "vision", "content": analysis[:300]},
        {"type": "thinking_end", "agent": "vision"},
    ]
    enriched = (
        f"请分析这张图片({img_name})的视觉内容。以下是AI的图片描述，请结合用户需求给出专业分析：\n"
        f"{analysis}\n[图片路径:{str(img_path)}]\n\n"
        f"用户的原始说明：{message.replace(f'[img:{img_name}]', '').strip() or '请分析这张图片的内容'}"
    )
    return enriched, events


def _recall_memory(message: str) -> tuple[str, list[dict]]:
    """Retrieve episodic and semantic memory relevant to the query.

    Returns ``(memory_context_string, sse_events_to_emit)``.
    """
    episodes = _memory.recall_episodes(message)
    facts = _memory.recall_facts()
    if not (facts or episodes):
        return "", []

    fact_str = "; ".join(f"{f['key']}={f['value']}" for f in facts[:5])
    ep_str = "; ".join(e["summary"][:60] for e in episodes[:2])
    ctx = f"\n[历史记忆] 关键事实: {fact_str}\n历史摘要: {ep_str}"
    events = [{
        "type": "memory_recall",
        "facts": facts[:5],
        "episodes": [{"summary": e["summary"][:100]} for e in episodes[:2]],
    }]
    return ctx, events


def _parse_tool_calls(raw_calls: list[dict], step: int) -> list[dict]:
    """Normalize and validate LLM tool-call objects into a safe uniform shape."""
    safe = []
    for tc in raw_calls:
        try:
            tc_id = tc.get("id", f"tc_{step}_{len(safe)}")
            fn = tc.get("function", {})
            name = fn.get("name", "")
            if not name:
                continue
            safe.append({
                "id": tc_id,
                "type": "function",
                "function": {"name": name, "arguments": fn.get("arguments", "{}")},
            })
        except (AttributeError, TypeError):
            continue
    return safe


def _deduplicate_calls(safe_calls: list[dict], executed: set[str]) -> tuple[list[tuple], list[dict]]:
    """Split tool calls into (to-execute, already-executed) partitions.

    Already-executed calls are answered from cache so the LLM gets context
    without redundant API hits.
    Returns ``(pending_calls, skipped_events)``.
    """
    pending: list[tuple[str, str, dict]] = []
    skipped_events: list[dict] = []
    for tc in safe_calls:
        tool_name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"])
        except (json.JSONDecodeError, TypeError):
            args = {}
        if not isinstance(args, dict):
            args = {}

        args_key = hashlib.md5(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        dedup = f"{tool_name}:{args_key}"
        if dedup in executed:
            cache_key = hashlib.md5(
                f"{TOOL_TO_SERVER.get(tool_name, '')}.{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}".encode()
            ).hexdigest()
            cached_entry = _tool_cache.get(cache_key)
            cached_summary = ""
            if cached_entry:
                _, cached_val = cached_entry
                if isinstance(cached_val, dict):
                    cached_summary = compress_result(tool_name, cached_val)
            skipped_events.append({
                "tc_id": tc["id"],
                "content": cached_summary or "（缓存未命中，重新执行）",
                "skip_msg": f"⏭️ 跳过已执行的工具：{tool_name}",
            })
            continue
        executed.add(dedup)
        pending.append((tc["id"], tool_name, args))
    return pending, skipped_events


async def _execute_single_tool(
    tc_id: str, tool_name: str, server: str, args: dict, user_msg: str, trace: Any,
) -> dict:
    """Dispatch one tool call to the correct executor (MCP / internal / generated).

    Routing logic:
        ``server == "generated"``  → re-run LLM-generated code in sandbox
        ``server == "internal"``   → in-process handler (dispatcher.py)
        ``server`` is empty        → auto-generate a new tool on the fly
        otherwise                  → MCP microservice via cached SSE call
    """
    t_tool = time.time()
    if server == "generated":
        r = exec_generated(tool_name, args)
        if isinstance(r, dict) and "error" not in r:
            issues = check_result_quality(r, user_msg)
            if issues:
                logger.info("[generated] quality issue: %s, regenerating...", "; ".join(issues))
                delete_generated(tool_name)
                gen, r_new, _ = await generate_tool_with_retry(
                    f"修复以下工具代码以解决质量问题：{user_msg} -> {tool_name}", max_attempts=2,
                )
                if gen and r_new:
                    r = r_new
                    r["_generated_tool"] = gen["tool_name"]
                else:
                    r = {"error": f"工具质量验证失败：{issues[0]}"}
    elif server == "internal":
        r = await handle_internal_tool(tool_name, args, user_msg)
    elif not server:
        gen, r_try, _ = await generate_tool_with_retry(
            f"为以下需求自动生成工具：{user_msg} -> {tool_name}", max_attempts=2,
        )
        r = r_try if r_try else {"error": f"Unknown tool: {tool_name}"}
        if gen:
            r["_generated_tool"] = gen["tool_name"]
    else:
        r = await cached_mcp_call(server, tool_name, args)

    trace.add(f"tool:{tool_name}", str(server), int((time.time() - t_tool) * 1000))
    return r if isinstance(r, dict) else {"result": str(r)[:200]}


def _build_plan_header(plan: str) -> str:
    """Wrap the routing plan into an assistant message for the ReAct context."""
    return f"执行计划：\n{plan[:800]}\n\n请按计划执行，每步调一个工具。禁止输出代码块。"


_TOOL_FOLLOWUPS: dict[str, list[tuple[str, str]]] = {
    "precipitation_grid":  [("暴雨XXmm会不会淹", "flood_sim_3d"), ("XX年一遇设计暴雨", "design_storm"), ("天气预报查询", "weather_forecast")],
    "flood_sim_3d":        [("洪水风险评估", "flood_assessment"), ("建筑提取", "building_extract"), ("风险等级分区", "flood_risk_zones")],
    "flood_inundation_map":[("暴雨XXmm会不会淹", "flood_sim_3d"), ("洪水风险评估", "flood_assessment"), ("建筑提取", "building_extract")],
    "flood_assessment":    [("暴雨XXmm会不会淹", "flood_sim_3d"), ("风险等级分区", "flood_risk_zones"), ("建筑提取", "building_extract")],
    "flood_warning":       [("暴雨XXmm会不会淹", "flood_sim_3d"), ("洪水风险评估", "flood_assessment"), ("XX年一遇设计暴雨", "design_storm")],
    "flood_risk_zones":    [("暴雨XXmm会不会淹", "flood_sim_3d"), ("洪水风险评估", "flood_assessment"), ("建筑提取", "building_extract")],
    "dem_analyze":         [("流域提取", "watershed_delineate"), ("河网提取", "flow_accumulation"), ("点位查询高程", "point_query")],
    "point_query":         [("地形分析DEM", "dem_analyze"), ("地形剖面", "terrain_profile"), ("流域提取", "watershed_delineate")],
    "terrain_profile":     [("地形分析DEM", "dem_analyze"), ("点位查询高程", "point_query"), ("流域提取", "watershed_delineate")],
    "watershed_delineate": [("河网提取", "flow_accumulation"), ("地形分析DEM", "dem_analyze"), ("产汇流计算", "runoff_compute")],
    "flow_accumulation":   [("流域提取", "watershed_delineate"), ("地形分析DEM", "dem_analyze"), ("点位查询高程", "point_query")],
    "design_storm":        [("产汇流计算", "runoff_compute"), ("暴雨XXmm会不会淹", "flood_sim_3d"), ("降水降雨分析", "precipitation_grid")],
    "runoff_compute":      [("暴雨XXmm会不会淹", "flood_sim_3d"), ("XX年一遇设计暴雨", "design_storm"), ("降水降雨分析", "precipitation_grid")],
    "weather_forecast":    [("降水降雨分析", "precipitation_grid"), ("暴雨XXmm会不会淹", "flood_sim_3d"), ("卫星影像", "satellite_search")],
    "building_extract":    [("暴雨XXmm会不会淹", "flood_sim_3d"), ("洪水风险评估", "flood_assessment"), ("卫星影像", "satellite_search")],
    "satellite_search":    [("地形分析DEM", "dem_analyze"), ("建筑提取", "building_extract"), ("水体监测", "water_monitor")],
    "water_monitor":       [("水体变化", "water_change"), ("卫星影像", "satellite_search"), ("地形分析DEM", "dem_analyze")],
    "water_change":        [("卫星影像", "satellite_search"), ("水体监测", "water_monitor"), ("地形分析DEM", "dem_analyze")],
    "render_map":          [("暴雨XXmm会不会淹", "flood_sim_3d"), ("降水降雨分析", "precipitation_grid"), ("地形分析DEM", "dem_analyze")],
    "spatial_query":       [("缓冲区分析", "buffer"), ("叠加分析", "overlay"), ("坐标转换", "coordinate_transform")],
    "buffer":              [("叠加分析", "overlay"), ("空间查询", "spatial_query"), ("渲染地图", "render_map")],
    "overlay":             [("缓冲区分析", "buffer"), ("空间查询", "spatial_query"), ("渲染地图", "render_map")],
    "coordinate_transform":[("空间查询", "spatial_query"), ("缓冲区分析", "buffer"), ("渲染地图", "render_map")],
    "get_parameter":       [("产汇流计算", "runoff_compute"), ("暴雨XXmm会不会淹", "flood_sim_3d"), ("查规范防洪标准", "get_standard")],
    "get_standard":        [("暴雨参数查询", "get_parameter"), ("XX年一遇设计暴雨", "design_storm"), ("产汇流计算", "runoff_compute")],
    "swmm_simulate":       [("暴雨XXmm会不会淹", "flood_sim_3d"), ("XX年一遇设计暴雨", "design_storm"), ("洪水风险评估", "flood_assessment")],
    "hydrodynamic_2d_sim": [("暴雨XXmm会不会淹", "flood_sim_3d"), ("洪水风险评估", "flood_assessment"), ("风险等级分区", "flood_risk_zones")],
}


def _extract_location(query: str) -> str:
    for name in CITY_COORDS:
        if name in query:
            return name
    return ""


async def _generate_suggestions(query: str, tools_used: list[str]) -> list[str]:
    if not tools_used:
        return []
    loc = _extract_location(query)
    seen: set[str] = set()
    result: list[str] = []
    unmatched: list[str] = []
    for tool in tools_used:
        chain = _TOOL_FOLLOWUPS.get(tool)
        if chain:
            for label, _tool in chain:
                if label not in seen:
                    seen.add(label)
                    result.append(f"{loc}{label}" if loc else label)
        else:
            unmatched.append(tool)
    if len(result) >= 3:
        return result[:3]
    if unmatched:
        extra = await _llm_suggestions(query, unmatched)
        for s in extra:
            if s not in seen:
                seen.add(s)
                result.append(s)
    return result[:3]


async def _llm_suggestions(query: str, tools_used: list[str]) -> list[str]:
    tool_summary = "、".join(tools_used[:5])
    prompt = (
        f'用户问了："{query[:100]}"。已用工具：{tool_summary}。'
        f"请生成2-3个相关的后续分析方向，每个不超过25字。"
        f'仅返回JSON数组，如：["建议1","建议2"]'
    )
    try:
        content, _, _ = await call_llm(
            [{"role": "user", "content": prompt}],
            model=MODEL_AIR,
            use_tools=False,
            max_tokens_override=200,
        )
        match = re.search(r'\[.*?\]', content, re.DOTALL)
        if match:
            suggestions = json.loads(match.group())
            return [s[:25] for s in suggestions if isinstance(s, str)][:3]
    except Exception:
        pass
    return []


@router.get("/api/chat/stream")
async def chat_stream(q: str, history: str = "", workflows: str = ""):
    """Main chat endpoint — streams SSE events for the entire ReAct reasoning cycle."""

    async def _generate():
        message = q
        t_start = time.time()
        trace = new_trace(message)
        yield sse({"type": "start", "message": message})

        # ── 1. Enrich: image prefix → vision analysis ──
        message, img_events = await _resolve_image_prefix(message)
        for evt in img_events:
            yield sse(evt)

        # ── 2. Parse conversation history ──
        parsed_history = _parse_history(history)

        # ── 3. Recall episodic / semantic memory ──
        memory_ctx, mem_events = _recall_memory(message)
        for evt in mem_events:
            yield sse(evt)

        commonsense_ctx = inject_commonsense(message)

        # ── 4. UI-action shortcut (3D / TIN / quadtree) ──
        ui_force = detect_ui_action(message)
        if ui_force:
            yield sse({"type": "thinking_start", "agent": "react", "label": "🎯 智能操作"})
            yield sse({"type": "thinking", "agent": "react", "content": f"检测到操作意图：{ui_force}"})
            yield sse({"type": "thinking_end", "agent": "react"})
            yield sse({"type": "ui_action", "action": ui_force, "args": {"action": ui_force}})
            labels = {"open_3d": "正在打开3D地形视图...", "open_tin": "正在生成TIN三角网...", "open_quadtree": "正在生成四叉树网格..."}
            async for ch in stream_words(labels.get(ui_force, f"UI: {ui_force}")):
                yield sse({"type": "text", "content": ch})
            yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": 0, "trace": trace.to_dict()})
            return

        # ── 4b. Pipeline detection — AI-powered multi-step spatial deduction ──
        yield sse({"type": "thinking_start", "agent": "planner", "label": "🔬 分析任务复杂度"})
        pipeline_tpl = await detect_pipeline(message)
        yield sse({"type": "thinking_end", "agent": "planner"})
        if pipeline_tpl:
            loc = _extract_location(message)

            async def _pipeline_exec(tool_name: str, args: dict, user_msg: str):
                server = TOOL_TO_SERVER.get(tool_name, "")
                return await _execute_single_tool("pipeline", tool_name, server, args, user_msg, trace)

            tools_used: list[str] = []
            async for event in execute_pipeline(pipeline_tpl, message, loc, trace, _pipeline_exec):
                yield event
                if isinstance(event, str) and event.startswith("data:"):
                    try:
                        evt = json.loads(event[5:].strip())
                        if evt.get("type") == "pipeline_step" and evt.get("status") == "done":
                            sid = evt.get("step_id", 0) - 1
                            if 0 <= sid < len(pipeline_tpl["steps"]):
                                tn = pipeline_tpl["steps"][sid]["tool"]
                                if tn not in tools_used:
                                    tools_used.append(tn)
                    except (json.JSONDecodeError, TypeError):
                        pass

            suggestions = await _generate_suggestions(message, tools_used)
            if suggestions:
                yield sse({"type": "chain_suggestion", "suggestions": [{"label": s} for s in suggestions]})
            yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": 0, "tools_called": len(tools_used), "trace": trace.to_dict()})
            return

        # ── 5. Route: regex rules → compute override → LLM fallback ──
        yield sse({"type": "thinking_start", "agent": "planner", "label": "🗺️ 意图识别"})
        t_route = time.time()
        plan = await route(message, parsed_history)
        trace.add("route", plan[:80], int((time.time() - t_route) * 1000))

        plan_upper = plan.strip().upper()
        is_simple = plan_upper.startswith("SIMPLE")
        is_direct = plan_upper.startswith("DIRECT:")
        direct_tool = plan.split(":", 1)[1].strip() if is_direct else ""

        if is_simple:
            yield sse({"type": "thinking", "agent": "planner", "content": "简单问候，直接回复。"})
        elif is_direct:
            yield sse({"type": "thinking", "agent": "planner", "content": f"直接调用工具：{direct_tool}"})
        else:
            yield sse({"type": "thinking", "agent": "planner", "content": "🤖 分析中，选择合适工具..."})
        yield sse({"type": "thinking_end", "agent": "planner"})

        # ── 6. Build ReAct message context ──
        react_messages: list[dict] = [
            {"role": "system", "content": REACT_SYSTEM_PROMPT + memory_ctx + "\n" + commonsense_ctx},
            *parsed_history,
            {"role": "user", "content": message},
        ]
        if is_direct:
            react_messages.append({"role": "assistant", "content": f"我将直接调用 {direct_tool} 工具来完成您的需求。"})
        elif not is_simple and plan:
            react_messages.append({"role": "assistant", "content": _build_plan_header(plan)})

        react_max = 3 if is_simple else MAX_REACT_STEPS
        executed: set[str] = set()
        total_tools = 0
        tools_used: list[str] = []

        yield sse({"type": "thinking_start", "agent": "react", "label": "🧠 自主推理"})

        # ── 7. ReAct loop ──
        for step in range(1, react_max + 1):
            yield sse({"type": "thinking", "agent": "react", "content": f"━━━ 推理步骤 {step}/{react_max} ━━━"})

            try:
                content, reasoning, tool_calls = await call_llm(react_messages, model=MODEL_AIR)
            except Exception as e:
                yield sse({"type": "thinking", "agent": "react", "content": f"❌ LLM失败: {str(e)[:80]}"})
                break

            if reasoning:
                for line in reasoning.replace(chr(10), "\n").split("\n"):
                    if line.strip():
                        yield sse({"type": "thinking", "agent": "react", "content": f"💭 {line.strip()[:300]}"})
            else:
                yield sse({"type": "thinking", "agent": "react", "content": "💭 分析用户请求..."})

            # Content without tool calls → check if plan is done, then finalize
            if content and not tool_calls:
                is_multi_step = not is_simple and not is_direct
                plan_steps = len([l for l in plan.split("\n") if l.strip() and l.strip()[0].isdigit()])
                if is_multi_step and total_tools < plan_steps:
                    react_messages.append({"role": "user", "content": "计划未完成，请继续调用下一个工具。不要回复文字，只调工具。"})
                    yield sse({"type": "thinking", "agent": "react", "content": "⏩ 计划未完成，强制继续..."})
                    continue

                yield sse({"type": "thinking", "agent": "react", "content": f"✅ 推理完成，共{step}步，调用{total_tools}个工具"})
                yield sse({"type": "thinking_end", "agent": "react"})
                async for ch in stream_words(content):
                    yield sse({"type": "text", "content": ch})
                suggestions = await _generate_suggestions(message, tools_used)
                if suggestions:
                    yield sse({"type": "chain_suggestion", "suggestions": [{"label": s} for s in suggestions]})
                yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
                return

            if not tool_calls:
                yield sse({"type": "thinking_end", "agent": "react"})
                async for ch in stream_words("抱歉，我暂时无法处理您的请求。请描述具体的水利分析需求。"):
                    yield sse({"type": "text", "content": ch})
                yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
                return

            # Normalize tool calls
            safe_calls = _parse_tool_calls(tool_calls, step)
            if not safe_calls:
                yield sse({"type": "thinking_end", "agent": "react"})
                async for ch in stream_words("抱歉，工具调用格式异常。请重新描述您的需求。"):
                    yield sse({"type": "text", "content": ch})
                yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
                return

            react_messages.append({"role": "assistant", "content": content, "tool_calls": safe_calls})

            # Deduplicate + resolve cache hits
            pending, skipped = _deduplicate_calls(safe_calls, executed)
            for tc in safe_calls:
                tool_name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
                yield sse({"type": "thinking", "agent": "react", "content": f"🔧 调用 {tool_name}({json.dumps(args, ensure_ascii=False)[:100]})"})
            for skip in skipped:
                yield sse({"type": "thinking", "agent": "react", "content": skip["skip_msg"]})
                react_messages.append({"role": "tool", "tool_call_id": skip["tc_id"], "content": skip["content"]})

            # Execute all pending tools in parallel
            tasks = [
                (tc_id, tool_name, TOOL_TO_SERVER.get(tool_name, ""), args)
                for tc_id, tool_name, args in pending
            ]
            results_raw = await asyncio.gather(
                *[_execute_single_tool(tid, tn, srv, a, message, trace) for tid, tn, srv, a in tasks],
                return_exceptions=True,
            )

            # Process each result: validate → physics → debate → stream
            for (tc_id, tool_name, server, args), result in zip(tasks, results_raw):
                if isinstance(result, Exception):
                    result = {"error": str(result)[:200]}

                total_tools += 1
                if tool_name not in tools_used:
                    tools_used.append(tool_name)
                label = AGENT_LABELS.get(server, server)
                result_keys = list(result.keys()) if isinstance(result, dict) else []

                # Summary of what the result contains
                viz_parts = [k for k in ("geojson", "data_points", "table", "image_base64") if k in result_keys]
                if viz_parts:
                    yield sse({"type": "thinking", "agent": "react", "content": f"📊 {tool_name} 返回可视化数据：{' + '.join(viz_parts)}"})
                elif isinstance(result, dict) and "error" not in result:
                    yield sse({"type": "thinking", "agent": "react", "content": f"✅ {tool_name} 完成，字段：{result_keys}"})

                # Result validation
                valid, validation_msg = validate_result(tool_name, args, result if isinstance(result, dict) else {})
                if not valid:
                    yield sse({"type": "thinking", "agent": "reflect", "content": f"⚠️ 安全检查：{tool_name} 异常：{validation_msg}"})
                    yield sse({"type": "tool_error", "server": server, "tool": tool_name, "error": validation_msg})
                    result = {"error": f"结果验证失败：{validation_msg}", "original_keys": result_keys}

                # Physics sanity check
                physics_warnings = validate_physics(tool_name, result if isinstance(result, dict) else {})
                if physics_warnings:
                    yield sse({"type": "thinking", "agent": "physics", "content": f"⚠️ 物理校验：{'； '.join(physics_warnings)}"})

                # Multi-agent debate for critical tools
                if tool_name in CRITICAL_TOOLS and isinstance(result, dict) and "error" not in result:
                    debate = await debate_validate(message, tool_name, result)
                    consensus = debate["consensus"]
                    yield sse({"type": "debate", "critics": debate["critics"], "consensus": consensus})
                    if not consensus:
                        issues = [c.get("issue", "") for c in debate["critics"] if c.get("issue")]
                        yield sse({"type": "thinking", "agent": "debate", "content": f"🔍 辩论发现问题：{'； '.join(issues[:2])}"})

                # Stream tool card + summary to frontend
                yield sse({"type": "divider", "content": f"━━ Step {step}: {label} ▶ {tool_name}"})
                yield sse({"type": "tool_start", "server": server, "tool": tool_name, "step": total_tools, "react_step": step})
                yield sse({"type": "tool_result", "server": server, "tool": tool_name, "result": result, "elapsed_ms": 0})

                summary = format_tool_summary(server, tool_name, result)
                async for ch in stream_words(summary):
                    yield sse({"type": "text", "content": ch})

                # Compress result for LLM context (avoid token bloat)
                compressed = compress_result(tool_name, result) if isinstance(result, dict) else str(result)[:200]
                if not is_simple and not is_direct and plan:
                    compressed += f"\n\n[已完成{total_tools}个工具。请继续执行计划中的下一步工具调用，不要回复文字。]"
                react_messages.append({"role": "tool", "tool_call_id": tc_id, "content": compressed})

                # Record evolution telemetry for routing accuracy analysis
                _log_evolution(
                    query=message,
                    layer="L3",
                    tool=tool_name,
                    was_correct=isinstance(result, dict) and "error" not in result,
                )

            react_messages = trim_context(react_messages)
            yield sse({"type": "thinking", "agent": "react", "content": f"📊 已获取{len(pending)}个工具结果，继续推理..."})

        # ── 8. Max steps reached → summarize ──
        yield sse({"type": "thinking", "agent": "react", "content": f"⚠️ 已达最大推理步数({react_max})，总结回复"})
        yield sse({"type": "thinking_end", "agent": "react"})
        try:
            final_content, _, _ = await call_llm(react_messages, model=MODEL_AIR, use_tools=False)
            async for ch in stream_words(final_content):
                yield sse({"type": "text", "content": ch})
        except Exception:
            async for ch in stream_words("分析完成。如需更详细结果，请提出更具体的问题。"):
                yield sse({"type": "text", "content": ch})

        suggestions = await _generate_suggestions(message, tools_used)
        if suggestions:
            yield sse({"type": "chain_suggestion", "suggestions": [{"label": s} for s in suggestions]})
        yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": react_max, "tools_called": total_tools, "trace": trace.to_dict()})

    async def generate():
        t_start = time.time()
        try:
            async for event in _generate():
                yield event
        except Exception as e:
            logger.exception("[SSE] unhandled error in chat_stream")
            yield sse({"type": "error", "content": f"内部错误: {str(e)[:200]}"})
            yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": 0, "tools_called": 0})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
