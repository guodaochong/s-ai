from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
from typing import Any

import structlog

from app.config import (
    AGENT_LABELS, CRITICAL_TOOLS, MAX_REACT_STEPS, MODEL_AIR, MODEL_FLASH,
    REACT_SYSTEM_PROMPT, TOOL_TO_SERVER, _tool_cache, logger,
)
from app.llm import call_llm
from app.router import route
from app.store import conversations, memory
from app.tracing import new_trace
from app.utils import (
    compress_result, detect_ui_action, format_tool_summary, get_chain_suggestions,
    parse_text_tool_calls, sse, stream_words, trim_context,
)
from app.validators import debate_validate, inject_commonsense, validate_physics, validate_result

UPLOAD_DIR = __import__("pathlib").Path(__file__).parent.parent.parent / "data" / "uploads"
UPLOAD_IMG_DIR = __import__("pathlib").Path(__file__).parent.parent.parent / "data" / "upload_images"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_IMG_DIR.mkdir(parents=True, exist_ok=True)


async def chat_stream_generator(q: str, history: str = "", workflows: str = "", conv_id: int = 0):
    message = q
    if not conv_id:
        conv_id = conversations.get_or_create()
    conversations.save_message(conv_id, "user", message)
    t_start = time.time()
    trace = new_trace(message)
    logger.info("[SSE] >>> new chat request", conv_id=conv_id, message=message[:100])
    yield sse({"type": "start", "message": message, "conv_id": conv_id})

    if message.startswith("[img:"):
        img_name = message[5:].strip().rstrip("]").strip()
        img_path = UPLOAD_IMG_DIR / img_name
        if img_path.exists():
            img_b64 = base64.b64encode(img_path.read_bytes()).decode()
            yield sse({"type": "thinking_start", "agent": "vision", "label": "👁️ 图像分析"})
            from app.multimodal import analyze_image
            analysis = await analyze_image(img_b64)
            yield sse({"type": "thinking", "agent": "vision", "content": analysis[:300]})
            yield sse({"type": "thinking_end", "agent": "vision"})
            message = f"用户上传了图片({img_name})，AI分析结果: {analysis}\n\n用户问题: {message.replace(f'[img:{img_name}]', '').strip() or '请根据图片分析结果进行水利相关分析'}"

    parsed_history = []
    if history:
        try:
            parsed_history = json.loads(history)
        except (json.JSONDecodeError, TypeError):
            pass

    memory_ctx = ""
    episodes = memory.recall_episodes(message)
    facts = memory.recall_facts()
    if facts or episodes:
        fact_str = "; ".join(f"{f['key']}={f['value']}" for f in facts[:5])
        ep_str = "; ".join(e["summary"][:60] for e in episodes[:2])
        memory_ctx = f"\n[记忆] 已知: {fact_str}\n历史: {ep_str}"
        yield sse({"type": "memory_recall", "facts": facts[:5], "episodes": [{"summary": e["summary"][:100]} for e in episodes[:2]]})

    commonsense_ctx = inject_commonsense(message)

    ui_force = detect_ui_action(message)
    if ui_force:
        yield sse({"type": "thinking_start", "agent": "react", "label": "🧠 自主推理"})
        yield sse({"type": "thinking", "agent": "react", "content": f"检测到UI意图: {ui_force}"})
        yield sse({"type": "thinking_end", "agent": "react"})
        yield sse({"type": "ui_action", "action": ui_force, "args": {"action": ui_force}})
        labels = {"open_3d": "🛰️ 已为您打开三维地形查看器", "open_tin": "🔺 已生成TIN三角网", "open_quadtree": "🌳 已生成四叉树剖分"}
        async for ch in stream_words(labels.get(ui_force, f"UI: {ui_force}")):
            yield sse({"type": "text", "content": ch})
        yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": 0, "trace": trace.to_dict()})
        conversations.save_message(conv_id, "assistant", labels.get(ui_force, f"UI: {ui_force}"))
        return

    yield sse({"type": "thinking_start", "agent": "planner", "label": "📋 任务规划"})
    t_route_start = time.time()
    plan = await route(message, parsed_history)
    trace.add("route", plan[:80], int((time.time() - t_route_start) * 1000))
    plan_upper = plan.strip().upper()
    is_simple = plan_upper.startswith("SIMPLE")
    is_direct = plan_upper.startswith("DIRECT:")
    direct_tool = plan.split(":", 1)[1].strip() if is_direct else ""
    if is_simple:
        yield sse({"type": "thinking", "agent": "planner", "content": "简单查询，直接执行"})
    elif is_direct:
        yield sse({"type": "thinking", "agent": "planner", "content": f"建议工具: {direct_tool}"})
    else:
        yield sse({"type": "thinking", "agent": "planner", "content": f"📋 执行计划:\n{plan[:300]}"})
    yield sse({"type": "thinking_end", "agent": "planner"})

    react_messages: list[dict] = [
        {"role": "system", "content": REACT_SYSTEM_PROMPT + memory_ctx + "\n" + commonsense_ctx},
        *parsed_history,
        {"role": "user", "content": message},
    ]
    if is_direct:
        react_messages.append({"role": "assistant", "content": f"建议使用 {direct_tool} 工具。如果该工具不适合当前任务，请改用 auto_tool。"})
    elif not is_simple:
        plan_header = f"""已制定执行计划，你必须严格按顺序逐步执行全部步骤。不要跳过任何步骤，不要提前结束。

执行计划：
{plan[:800]}

规则：
1. 每步只调1-2个工具
2. 当前步骤的工具返回结果后，立即调下一步的工具
3. 不要重复调用已返回结果的工具
4. 全部步骤执行完毕后再总结回复
5. 即使某步结果不完美，也要继续执行下一步"""
        react_messages.append({"role": "assistant", "content": plan_header})
        react_messages.append({"role": "user", "content": "现在开始执行第1步。"})

    if is_simple:
        react_max = 2
    elif is_direct and direct_tool not in ("auto_tool", "storm_flood_pipeline"):
        react_max = 3
    else:
        react_max = MAX_REACT_STEPS
    executed: set[str] = set()
    total_tools = 0

    yield sse({"type": "thinking_start", "agent": "react", "label": "🧠 自主推理"})

    for step in range(1, react_max + 1):
        yield sse({"type": "thinking", "agent": "react", "content": f"━━━ 推理步骤 {step}/{react_max} ━━━"})
        step_purpose = "分析用户意图并决定下一步操作" if step == 1 else "根据上一步结果继续推理"
        yield sse({"type": "thinking", "agent": "react", "content": f"📋 当前目标: {step_purpose}"})

        try:
            content, reasoning, tool_calls = await call_llm(react_messages, model=MODEL_FLASH)
        except Exception as e:
            logger.error("[SSE] LLM call failed in ReAct loop", step=step, error=f"{type(e).__name__}: {str(e)[:100]}")
            yield sse({"type": "thinking", "agent": "react", "content": f"❌ LLM失败: {str(e)[:80]}"})
            break

        if reasoning:
            lines = reasoning.replace(chr(10), '\n').split('\n')
            for line in lines:
                line = line.strip()
                if line:
                    yield sse({"type": "thinking", "agent": "react", "content": f"💭 {line[:300]}"})
        else:
            yield sse({"type": "thinking", "agent": "react", "content": "💭 正在深度分析用户请求与上下文..."})

        if content and not tool_calls:
            text_tc = parse_text_tool_calls(content)
            if text_tc:
                tool_calls = text_tc
                yield sse({"type": "thinking", "agent": "react", "content": f"🔄 从文本中恢复{len(text_tc)}个工具调用: {', '.join(t['function']['name'] for t in text_tc)}"})
                logger.info("[SSE] recovered tool_calls from text", count=len(text_tc))
            else:
                is_multi_step = not is_simple and not is_direct
                if is_multi_step and total_tools < len([l for l in plan.split('\n') if l.strip() and l.strip()[0].isdigit()]):
                    react_messages.append({"role": "user", "content": "计划未完成，请继续调用下一个工具。不要回复文字，只调工具。"})
                    yield sse({"type": "thinking", "agent": "react", "content": "⏩ 计划未完成，强制继续..."})
                    continue
                yield sse({"type": "thinking", "agent": "react", "content": f"✅ 推理完成，共{step}步，调用{total_tools}个工具"})
                yield sse({"type": "thinking_end", "agent": "react"})
                async for ch in stream_words(content):
                    yield sse({"type": "text", "content": ch})
                yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
                conversations.save_message(conv_id, "assistant", content)
                return

        if not tool_calls:
            yield sse({"type": "thinking_end", "agent": "react"})
            async for ch in stream_words("抱歉，我暂时无法处理您的请求。请描述具体的水利分析需求。"):
                yield sse({"type": "text", "content": ch})
            yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
            conversations.save_message(conv_id, "assistant", "抱歉，我暂时无法处理您的请求。请描述具体的水利分析需求。")
            return

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
        safe_tool_calls = []
        for tc in tool_calls:
            try:
                tc_id = tc.get("id", f"tc_{step}_{len(safe_tool_calls)}")
                fn = tc.get("function", {})
                name = fn.get("name", "")
                arguments = fn.get("arguments", "{}")
                if not name:
                    continue
                safe_tool_calls.append({"id": tc_id, "type": "function", "function": {"name": name, "arguments": arguments}})
            except (AttributeError, TypeError):
                continue
        if not safe_tool_calls:
            yield sse({"type": "thinking_end", "agent": "react"})
            async for ch in stream_words("抱歉，工具调用格式异常。请重新描述您的需求。"):
                yield sse({"type": "text", "content": ch})
            yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
            conversations.save_message(conv_id, "assistant", "抱歉，工具调用格式异常。请重新描述您的需求。")
            return
        assistant_msg["tool_calls"] = safe_tool_calls
        react_messages.append(assistant_msg)

        deduped_calls = []
        for tc in safe_tool_calls:
            tool_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, TypeError):
                args = {}
            if not isinstance(args, dict):
                args = {}
            args_summary = json.dumps(args, ensure_ascii=False)[:100]
            tool_label = AGENT_LABELS.get(TOOL_TO_SERVER.get(tool_name, ""), tool_name)
            yield sse({"type": "thinking", "agent": "react", "content": f"🔍 选择工具: {tool_label} → {tool_name}"})
            yield sse({"type": "thinking", "agent": "react", "content": f"📋 调用参数: {args_summary}"})
            yield sse({"type": "thinking", "agent": "react", "content": f"🎯 执行: {tool_name}({args_summary})"})
            args_key = hashlib.md5(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            dedup = f"{tool_name}:{args_key}"
            if dedup in executed:
                yield sse({"type": "thinking", "agent": "react", "content": f"⏭️ 跳过重复: {tool_name}"})
                cache_lookup = hashlib.md5(f"{TOOL_TO_SERVER.get(tool_name, '')}.{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}".encode()).hexdigest()
                cached_entry = _tool_cache.get(cache_lookup)
                cached_summary = ""
                if cached_entry:
                    _, cached_val = cached_entry
                    if isinstance(cached_val, dict):
                        cached_summary = compress_result(tool_name, cached_val)
                react_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": cached_summary or "该工具已执行过，结果已在上方。请继续执行下一步。"})
                continue
            executed.add(dedup)
            deduped_calls.append((tc["id"], tool_name, args))

        tasks = [(tc_id, tool_name, TOOL_TO_SERVER.get(tool_name, ""), args) for tc_id, tool_name, args in deduped_calls]

        from app.mcp_client import cached_mcp_call
        from app.tools import check_result_quality, delete_generated, exec_generated, generate_tool_with_retry
        from app.services import handle_internal_tool

        async def _exec_task(tc_id: str, tool_name: str, server: str, args: dict, user_msg: str) -> dict:
            t_tool = time.time()
            logger.info("[ExecTask] >>> start", tool=tool_name, server=server)
            if server == "generated":
                r = exec_generated(tool_name, args)
                if isinstance(r, dict) and "error" not in r:
                    quality_issues = check_result_quality(r, user_msg)
                    if quality_issues:
                        delete_generated(tool_name)
                        gen, r_new, _ = await generate_tool_with_retry(f"用户需要: {user_msg} -> {tool_name}", max_attempts=3)
                        if gen and r_new:
                            r = r_new
                            r["_generated_tool"] = gen["tool_name"]
                        else:
                            r = {"error": f"重新生成失败: {quality_issues[0]}"}
            elif server == "internal":
                r = await handle_internal_tool(tool_name, args, user_msg)
            elif not server:
                gen, r_try, _ = await generate_tool_with_retry(f"用户需要: {user_msg} -> {tool_name}", max_attempts=3)
                if gen and r_try:
                    r = r_try
                    r["_generated_tool"] = gen["tool_name"]
                else:
                    r = {"error": f"Unknown tool: {tool_name}"}
            else:
                r = await cached_mcp_call(server, tool_name, args)
            elapsed_tool = int((time.time() - t_tool) * 1000)
            trace.add(f"tool:{tool_name}", str(server), elapsed_tool)
            return r

        results_raw = await asyncio.gather(*[_exec_task(tc_id, n, s, a, message) for tc_id, n, s, a in tasks], return_exceptions=True)

        for i, ((tc_id, tool_name, server, args), result) in enumerate(zip(tasks, results_raw)):
            if isinstance(result, Exception):
                result = {"error": str(result)[:200]}

            total_tools += 1
            label = AGENT_LABELS.get(server, server)

            result_keys = list(result.keys()) if isinstance(result, dict) else []
            has_geojson = "geojson" in result_keys
            has_data = "data_points" in result_keys
            has_table = "table" in result_keys
            has_img = "image_base64" in result_keys
            viz_parts = []
            if has_geojson: viz_parts.append("GeoJSON")
            if has_data: viz_parts.append("曲线图")
            if has_table: viz_parts.append("表格")
            if has_img: viz_parts.append("图片")
            if isinstance(result, dict) and "error" in result:
                err_msg = result["error"][:120]
                yield sse({"type": "thinking", "agent": "react", "content": f"❌ {tool_name} 执行失败: {err_msg}"})
                yield sse({"type": "thinking", "agent": "react", "content": f"🔄 考虑切换其他工具或调整参数重试"})
            elif viz_parts:
                yield sse({"type": "thinking", "agent": "react", "content": f"📊 {tool_name} 返回结果包含: {' + '.join(viz_parts)}"})
            elif isinstance(result, dict):
                key_list = ", ".join(result_keys[:6])
                yield sse({"type": "thinking", "agent": "react", "content": f"✅ {tool_name} 执行成功"})

            valid, validation_msg = validate_result(tool_name, args, result if isinstance(result, dict) else {})
            if not valid:
                yield sse({"type": "thinking", "agent": "reflect", "content": f"🔍 反思: {tool_name}结果异常 — {validation_msg}"})
                yield sse({"type": "tool_error", "server": server, "tool": tool_name, "error": validation_msg})
                result = {"error": f"验证失败: {validation_msg}"}

            physics_warnings = validate_physics(tool_name, result if isinstance(result, dict) else {})
            if physics_warnings:
                yield sse({"type": "thinking", "agent": "physics", "content": f"⚡ 物理校验: {'; '.join(physics_warnings)}"})

            if tool_name in CRITICAL_TOOLS and isinstance(result, dict) and "error" not in result:
                debate = await debate_validate(message, tool_name, result)
                if not debate["consensus"]:
                    issues = [c.get("issue", "") for c in debate["critics"] if c.get("issue")]
                    yield sse({"type": "debate", "critics": debate["critics"], "consensus": False})
                else:
                    yield sse({"type": "debate", "critics": debate["critics"], "consensus": True})

            yield sse({"type": "divider", "content": f"⚡ Step {step}: {label} → {tool_name}"})
            yield sse({"type": "tool_start", "server": server, "tool": tool_name, "step": total_tools, "react_step": step})
            if isinstance(result, dict) and result.get("geojson"):
                yield sse({"type": "geojson_data", "tool": tool_name, "geojson": result["geojson"]})
                sse_result = {k: v for k, v in result.items() if k != "geojson"}
                sse_result["geojson_summary"] = f"FeatureCollection({len(result['geojson'].get('features', []))} features)"
            else:
                sse_result = result
            yield sse({"type": "tool_result", "server": server, "tool": tool_name, "result": sse_result, "elapsed_ms": 0})

            chain_hint = get_chain_suggestions(tool_name)
            if chain_hint and isinstance(result, dict) and "error" not in result:
                yield sse({"type": "chain_suggestion", "tool": tool_name, "suggestions": chain_hint})

            summary = format_tool_summary(server, tool_name, result)
            async for ch in stream_words(summary):
                yield sse({"type": "text", "content": ch})

            compressed = compress_result(tool_name, result) if isinstance(result, dict) else str(result)[:200]
            if not is_simple and not is_direct and plan:
                compressed += f"\n\n[已完成{total_tools}个工具。请继续执行计划中的下一步工具调用，不要回复文字。]"
            react_messages.append({"role": "tool", "tool_call_id": tc_id, "content": compressed})

        react_messages = trim_context(react_messages)
        yield sse({"type": "thinking", "agent": "react", "content": f"📊 已获取{len(deduped_calls)}个工具结果，继续推理..."})

    yield sse({"type": "thinking", "agent": "react", "content": f"⚠️ 已达最大推理步数({react_max})，总结回复"})
    yield sse({"type": "thinking_end", "agent": "react"})
    max_final = "分析完成。如需更详细结果，请提出更具体的问题。"
    try:
        final_content, _, _ = await call_llm(react_messages, model=MODEL_AIR, use_tools=False)
        async for ch in stream_words(final_content):
            yield sse({"type": "text", "content": ch})
        conversations.save_message(conv_id, "assistant", final_content)
    except Exception:
        async for ch in stream_words(max_final):
            yield sse({"type": "text", "content": ch})
        conversations.save_message(conv_id, "assistant", max_final)

    yield sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": react_max, "tools_called": total_tools, "trace": trace.to_dict()})
    logger.info("[SSE] <<< max steps reached", react_max=react_max, tools=total_tools, elapsed_ms=int((time.time() - t_start) * 1000))
