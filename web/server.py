from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import structlog
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).parent.parent / ".env")

logger = structlog.get_logger(__name__)

ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")

SYSTEM_PROMPT = """你是 S-AI 水利空间智能体平台的调度中心，具备专业水利工程师和空间分析师的双重身份。回复要专业、简洁、有条理。\n\n【平台能力】\n- 8个MCP服务器，36个水利+空间分析工具\n- 真实DEM数据（甘肃迭部0.5m高精度地形）\n- LLM意图路由 + 拖拽工作流编排 + 自然语言调用\n- 8个智能体协同：Knowledge知识库/Hydro水力/GIS地理/Flood洪水/Raster地形/Map地图/Data数据/Router调度\n\n【交互规则】\n- 用户问候（"你好/在吗"）→ 专业自我介绍+能力列表+引导提问\n- 用户提需求 → 选择合适工具，从描述中提取实际参数\n- 用户在地图上点击 → 提示"已捕获坐标，正在执行空间情报分析..."\n- 任何错误时 → 不要沉默或重试3次，要明确告诉用户错在哪 + 给出替代方案\n- 涉及具体数值计算时，**必须调用工具**获得真实结果，不要凭空捏造数字\n\n可用工具列表：
1. knowledge.get_parameter - 查询水利参数
   参数: parameter_name(manning_n/scs_cn/design_storm), conditions(dict, 如{"surface":"混凝土管道"}或{"city":"北京"})
2. knowledge.search - 知识库搜索
   参数: query(str)
3. hydro.design_storm - 生成设计暴雨雨型
   参数: city(beijing/shanghai/shenzhen/guangzhou/chengdu), return_period(int, 重现期年数), duration_minutes(int, 降雨历时)
4. hydro.runoff_compute - SCS-CN径流计算
   参数: rainfall_mm(float, 降雨量毫米), curve_number(int, CN值, 城市50-70/郊区30-50/农田20-40), drainage_area_ha(float, 汇水面积公顷)
5. hydro.swmm_create_model - 创建SWMM排水模型
   参数: project_name(str), area_hectares(float), impervious_percent(float, 不透水面积百分比), n_subcatchments(int, 子汇水区数量)
6. hydro.swmm_simulate - 运行SWMM模拟
   参数: project_name(str), rainfall_mm_hr(float, 降雨强度mm/h), duration_min(int)
7. hydro.calibrate_suggest - 模型率定建议
   参数: observed_peak_flow(float), simulated_peak_flow(float), nash_sutcliffe(float)
8. flood.flood_inundation_map - 生成淹没范围图（地图上渲染GeoJSON）
   参数: center_lng(float), center_lat(float), radius_m(float, 淹没半径米), max_depth_m(float, 最大水深米)
9. flood.flood_assessment - 内涝风险评估（数值计算）
   参数: rainfall_mm(float), drainage_area_ha(float), impervious_pct(float, 不透水比例), pipe_capacity_cms(float, 管道排水能力)
10. flood.drainage_assessment - 排水能力校核（Manning公式）
    参数: pipe_diameter_m(float, 管径米), pipe_slope(float, 坡度), manning_n(float, 糙率0.01-0.03), design_flow_cms(float, 设计流量)
11. flood.flood_warning - 洪水预警
    参数: current_rainfall_mm_hr(float), forecast_rainfall_mm_hr(float), soil_saturation_pct(float, 0-100), drainage_utilization_pct(float, 0-100)
12. flood.flood_risk_zones - 风险分区
    参数: population_density(float, 人/km2), infrastructure_density(float, 0-1)
13. flood.hydrodynamic_2d_sim - 二维水动力淹没演进模拟（LISFLOOD-FP diffusive wave）
    参数: duration_hours(float, 模拟时长), output_interval_hours(float, 输出间隔), rainfall_pattern(str, uniform/triangular/chicago), total_rainfall_mm(float)
    返回多帧GeoJSON等值线，前端自动动画播放。当用户提到水动力、淹没演进、洪水演进、动态模拟时调用此工具
13. raster.dem_analyze - DEM地形分析（坡度/坡向/流向）
    参数: compute_slope(bool), compute_aspect(bool), compute_flowdir(bool)
    当用户提到坡度、地形、DEM分析时必须调用此工具
14. raster.watershed_delineate - 流域提取
    参数: outlet_lng(float), outlet_lat(float)
15. raster.terrain_profile - 地形剖面
    参数: start_lng(float), start_lat(float), end_lng(float), end_lat(float)
16. raster.flow_accumulation - 汇流累积分析
    参数: threshold_cells(int)
 17. gis.buffer - 缓冲区分析
    参数: distance(float, 公里)
 18. gis.overlay - 叠加分析
    参数: operation(intersection/union/difference)
 19. gis.import_network - 导入上传的管网GIS数据
    参数: file_name(str, 上传文件名) 或 file_path(str, 完整路径)
 20. raster.point_query - 空间情报点查询（点击地图上某点获取完整空间属性）
    参数: lng(float), lat(float), search_radius_m(float, 默认500)
    用于查询某点的高程/坡度/坡向/曲率/TPI/TRI/地形分类
 21. raster.tin_generate - TIN三角网生成（不规则三角网剖分）
    参数: lng_min/lng_max/lat_min/lat_max, max_points(int), refine_steep(bool)
 22. raster.quadtree_subdivide - 四叉树自适应剖分（基于地形复杂度）
    参数: lng_min/lng_max/lat_min/lat_max, max_depth(int), variance_threshold(float)

UI操作指令（直接触发前端动作，不调用工具）：
- 用户说"3D/三维/立体/heightmap/三维场景/三维地形" → 返回 {"ui_action": "open_3d", "reply": "🛰️ 正在为您打开三维地形查看器..."}
- 用户说"三角网/TIN/不规则三角网" → 返回 {"ui_action": "open_tin", "reply": "🔺 正在生成TIN三角网..."}
- 用户说"四叉树/Quadtree/嵌套剖分/自适应剖分" → 返回 {"ui_action": "open_quadtree", "reply": "🌳 正在生成四叉树剖分..."}
- ⚠️ 关键判断规则：
  * "三维场景/3D看/立体可视化" → open_3d (UI)，**不是** dem_analyze
  * "三角网/TIN" → open_tin (UI)
  * "坡度/坡向/高程/统计" → dem_analyze (工具)
  * "剖面/断面" → terrain_profile (工具)
  * 任何UI操作关键词出现时，**优先返回ui_action**，不要调用工具

参数提取规则：
- 从用户描述中提取实际数值作为参数，不要用默认值
- 面积: "200公顷"→200, "5平方公里"→500, "2km2"→200
- 降雨: "100mm"→100, "50年一遇"→return_period=50, "100年一遇"→return_period=100
- 城市: "北京"→city="beijing", "上海"→"shanghai", "深圳"→"shenzhen", "广州"→"guangzhou", "成都"→"chengdu"
- 不透水: "城市中心"→70-80, "城区"→55-70, "郊区"→30-50, "农村"→10-25
- 管径: "DN800"→0.8m, "DN1000"→1.0m, "DN600"→0.6m（这是管径，不是排水能力）
- 坐标默认北京 116.397, 39.908，用户指定其他城市时调整
- 用户没给的参数根据上下文合理推断，不要用固定默认值

重要规则：
- 如果用户描述中缺少关键参数（如面积、降雨量等），不要自己编造数值
- 应该先回复用户，列出缺少的参数并请用户补充
- 回复格式：{"reply": "为了进行XX分析，还需要以下信息：\n1. [缺少的参数1]（说明）\n2. [缺少的参数2]（说明）\n\n请补充以上信息。"}
- 只有当参数基本齐全时才调用工具
- 简单问候、闲聊等不需要工具的，直接回复即可
- 你是水利工程师角色，回复要专业、准确、有条理

回复格式（严格JSON，不要加注释，不要加```代码块标记，直接输出JSON）：
- 需要调用工具时：{"tools": [{"server": "flood", "tool": "flood_inundation_map", "arguments": {"radius_m": 2000, "max_depth_m": 2.0}}]}
- 注意：tool字段只写工具名，不要加server前缀。正确："tool":"design_storm"，错误："tool":"hydro.design_storm"
- 纯文字回复时：{"reply": "你的回答"}
- UI动作（3D/TIN/Quadtree）时：{"ui_action": "open_3d", "reply": "简短说明"}
- 可以同时调用多个工具，按顺序串行执行
- 当用户提到内涝/淹没/洪水/积水时，必须同时调用 flood.flood_inundation_map 在地图上渲染
- 当用户提到流域/汇水时，必须同时调用 raster.watershed_delineate 在地图上渲染
- 用户提到水位时，从消息中提取水位值传入 water_level_m 参数
- 用户提到"3D/三维/立体场景"时，**绝不能**调用 raster.dem_analyze！必须返回 ui_action: open_3d
- DEM数据位于甘肃迭部(104.89°E, 33.19°N)，flood_inundation_map 无需传坐标，会自动定位有效DEM区域

编排工作流调用规则：
- 用户说"跑/执行/运行XX流程/方案/工作流"时，如果XX匹配已知编排方案名称，回复：{"reply": "好的，正在执行【执行流程：XX】编排方案..."}
- 已知的编排方案包括：地形分析（DEM坡度→河网提取→流域提取→地形渲染）、洪水分析（DEM分析→淹没模拟→洪水预警→风险分区）
- 用户也可以自定义编排方案并在对话中调用
- 回复中必须包含【执行流程：方案名】标记，系统会自动识别并执行对应的编排方案"""

MCP_SERVERS = {
    "gis": "http://127.0.0.1:5001",
    "data": "http://127.0.0.1:5002",
    "knowledge": "http://127.0.0.1:5003",
    "map": "http://127.0.0.1:5004",
    "hydro": "http://127.0.0.1:5005",
    "flood": "http://127.0.0.1:5006",
    "raster": "http://127.0.0.1:5007",
}

async def _call_llm(messages: list[dict]) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {ZHIPUAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "glm-4-air-250414", "messages": messages, "temperature": 0.1, "max_tokens": 1024}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post("https://open.bigmodel.cn/api/coding/paas/v4/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content", "") or ""
        reasoning = msg.get("reasoning_content", "") or ""
        return content, reasoning


def _detect_ui_action(msg: str) -> str:
    m = msg.lower()
    if any(k in msg for k in ["三角网", "TIN", "不规则三角"]):
        return "open_tin"
    if any(k in msg for k in ["四叉树", "Quadtree", "嵌套剖分", "自适应剖分"]):
        return "open_quadtree"
    if any(k in msg for k in ["三维", "3D", "立体", "heightmap", "立体场景", "三维场景", "立体地形", "三维地形"]):
        return "open_3d"
    return ""


def _parse_llm_response(text: str) -> tuple[list[tuple[str, str, dict]], str]:
    import re
    try:
        text = text.strip()
        # extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        if json_match:
            text = json_match.group(1).strip()
        # find raw JSON object if no code block
        if not text.startswith('{'):
            brace_match = re.search(r'\{[\s\S]*\}', text)
            if brace_match:
                text = brace_match.group(0)
        # strip JS-style comments
        text = re.sub(r'//.*?(?=\n|")', '', text)
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        return [], text

    tools = []
    reply = data.get("reply", "")
    ui_action = data.get("ui_action", "")
    if ui_action:
        tools.append(("ui", "__ui_action__", {"action": ui_action}))
    for t in data.get("tools", []):
        server = t.get("server", "")
        tool = t.get("tool", "")
        args = t.get("arguments", {})
        clean_args = {}
        for k, v in args.items():
            if isinstance(k, str):
                clean_args[k] = v
        if server and tool:
            if tool.startswith(server + "."):
                tool = tool[len(server) + 1:]
            tools.append((server, tool, clean_args))
    return tools, reply


THINKING_STEPS = {
    "knowledge": ["解析查询意图...", "识别关键实体: {entities}", "匹配参数表: {table}", "检索条件: {conditions}", "调用 mcp-knowledge.{tool}...", "解析返回数据...", "格式化输出..."],
    "gis": ["解析空间分析需求...", "提取几何参数: {params}", "确定操作: {operation}", "调用 mcp-gis.{tool}...", "处理几何运算...", "验证结果有效性...", "空间分析完成。"],
    "map": ["解析可视化需求...", "准备图层数据...", "配置渲染样式...", "调用 mcp-map.{tool}...", "生成图像...", "可视化完成。"],
    "data": ["解析数据操作需求...", "检查数据源...", "调用 mcp-data.{tool}...", "处理结果..."],
    "hydro": ["解析水文分析需求...", "确定分析方法: {operation}", "准备水文参数...", "调用 mcp-hydro.{tool}...", "计算产汇流...", "水文分析完成。"],
    "flood": ["解析内涝分析需求...", "评估排水能力...", "调用 mcp-flood.{tool}...", "计算淹没范围...", "风险等级评定...", "内涝分析完成。"],
    "raster": ["解析地形分析需求...", "加载DEM数据...", "调用 mcp-raster.{tool}...", "计算地形因子...", "地形分析完成。"],
}

app = FastAPI(title="S-AI Web API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/")
async def index():
    from starlette.responses import FileResponse as FR
    resp = FR(Path(__file__).parent / "index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "web", "tools": 0}


@app.get("/api/servers")
async def list_servers():
    results: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in MCP_SERVERS.items():
            try:
                resp = await client.get(f"{url}/health")
                results[name] = {"url": url, "status": "healthy", "info": resp.json()}
            except Exception:
                results[name] = {"url": url, "status": "offline", "info": None}
    return results


UPLOAD_DIR = Path(__file__).parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/upload")
async def upload_file(file: UploadFile = FastAPIFile(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in (".geojson", ".json", ".shp", ".zip", ".gpkg", ".kml", ".csv"):
        return {"error": f"Unsupported format: {ext}. Accepted: .geojson, .json, .shp, .zip, .gpkg, .kml, .csv"}
    dest = UPLOAD_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)
    info: dict[str, Any] = {"filename": file.filename, "size_bytes": len(content), "path": str(dest)}
    if ext in (".geojson", ".json"):
        try:
            data = json.loads(content)
            if data.get("type") == "FeatureCollection":
                n = len(data.get("features", []))
                info["format"] = "GeoJSON"
                info["features"] = n
                if n > 0:
                    geom_types = set()
                    for f in data["features"][:50]:
                        g = f.get("geometry", {})
                        if g.get("type"):
                            geom_types.add(g["type"])
                    info["geometry_types"] = sorted(geom_types)
            elif data.get("type") in ("Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"):
                info["format"] = "GeoJSON"
                info["features"] = 1
                info["geometry_types"] = [data["type"]]
        except json.JSONDecodeError:
            pass
    return info


@app.get("/api/uploads")
async def list_uploads():
    files = []
    for f in sorted(UPLOAD_DIR.iterdir()):
        if f.is_file():
            stat = f.stat()
            files.append({"filename": f.name, "size_bytes": stat.st_size, "modified": stat.st_mtime})
    return {"files": files, "upload_dir": str(UPLOAD_DIR)}


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _extract_entities(msg: str) -> str:
    kw_map = {"糙率": "曼宁糙率", "manning": "曼宁糙率", "HDPE": "管材HDPE", "暴雨": "设计暴雨", "重现期": "重现期P", "CN": "SCS-CN", "曲线": "SCS-CN", "缓冲": "缓冲分析", "叠加": "叠加分析", "交集": "几何交集", "面积": "几何属性", "地图": "地图渲染", "验证": "数据验证", "质量": "数据质量"}
    found = [v for k, v in kw_map.items() if k in msg.lower()]
    return ", ".join(found[:5]) or "通用查询"


@app.get("/api/heightmap")
async def heightmap_proxy(size: int = 256):
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(f"http://127.0.0.1:5007/api/heightmap", params={"size": size})
        return resp.json()


@app.get("/api/chat/stream")
async def chat_stream(q: str, history: str = "", workflows: str = ""):
    async def generate():
        message = q
        t_start = time.time()
        yield _sse({"type": "start", "message": message})

        parsed_history = []
        if history:
            try:
                parsed_history = json.loads(history)
            except (json.JSONError, TypeError):
                pass

        wf_names = []
        if workflows:
            try:
                wf_names = json.loads(workflows)
            except (json.JSONError, TypeError):
                pass

        dynamic_prompt = SYSTEM_PROMPT
        if wf_names:
            dynamic_prompt += f"\n\n用户已保存的自定义编排方案：{', '.join(wf_names)}。如果用户提到执行/运行/调用这些方案名，回复中必须包含【执行流程：方案名】标记。"

        # === Phase 1: Router Thinking ===
        yield _sse({"type": "thinking_start", "agent": "router", "label": "Router 总指挥"})
        for step in ["接收用户指令...", f"原始输入: \"{message}\""]:
            yield _sse({"type": "thinking", "agent": "router", "content": step})
            await asyncio.sleep(0.15)

        matched: list[tuple[str, str, dict]] = []
        llm_reply = ""
        entities = _extract_entities(message)

        # LLM routing (primary)
        if ZHIPUAI_API_KEY:
            yield _sse({"type": "thinking", "agent": "router", "content": "调用 GLM-5.1 意图识别..."})
            try:
                llm_response, llm_reasoning = await _call_llm([
                    {"role": "system", "content": dynamic_prompt},
                    *parsed_history,
                    {"role": "user", "content": message},
                ])
                if llm_reasoning:
                    summary = llm_reasoning.replace("\n", " ").strip()[:150]
                    yield _sse({"type": "thinking", "agent": "router", "content": f"💭 {summary}..."})
                matched, llm_reply = _parse_llm_response(llm_response)
                if matched:
                    yield _sse({"type": "thinking", "agent": "router", "content": f"GLM 选择 {len(matched)} 个工具: {', '.join(f'{s}.{t}' for s,t,_ in matched)}"})
                elif llm_reply:
                    yield _sse({"type": "thinking", "agent": "router", "content": "GLM 直接回复"})

                ui_force = _detect_ui_action(message)
                if ui_force:
                    matched = [("ui", "__ui_action__", {"action": ui_force})]
                    llm_reply = ""
                    yield _sse({"type": "thinking", "agent": "router", "content": f"检测到UI意图，强制路由: {ui_force}"})
                elif matched and any(t in ("dem_analyze", "dem_render") for _, t, _ in matched):
                    for kw in ("三维", "3D", "立体", "heightmap", "立体场景", "三维场景", "立体地形", "三维地形"):
                        if kw in message and not any(k in message for k in ("坡度", "坡向", "分析", "高程统计", "stats", "统计")):
                            matched = [("ui", "__ui_action__", {"action": "open_3d"})]
                            llm_reply = ""
                            yield _sse({"type": "thinking", "agent": "router", "content": f"含'{kw}'且非分析意图 → 强制3D视图"})
                            break
                if matched and any(t == "hydrodynamic_2d_sim" for _, t, _ in matched):
                    matched = [(s, t, a) for s, t, a in matched if s != "hydro"]
            except Exception as e:
                yield _sse({"type": "thinking", "agent": "router", "content": f"GLM 失败: {str(e)[:60]}，回退关键词"})

        # Keyword fallback (also when LLM returned reply without tools)
        if not matched:
            kw_matched = _keyword_fallback(message)
            if kw_matched:
                matched = kw_matched
                yield _sse({"type": "thinking", "agent": "router", "content": f"关键词匹配: {', '.join(f'{s}.{t}' for s,t,_ in matched)}"})

        if not matched and not llm_reply:
            yield _sse({"type": "thinking", "agent": "router", "content": "未匹配具体工具 → 通用回复"})
            yield _sse({"type": "thinking_end", "agent": "router"})
            async for ch in _stream_words("水利空间智能体已就绪\n\n我是S-AI，融合水利工程师与空间分析师的专业智能体平台。接入8个专项智能体、42个专业工具，基于甘肃迭部0.5m高精度DEM真实地形数据。\n\n🔹 地形与空间分析\n  · \"分析坡度坡向\" → DEM地形分析\n  · \"提取流域河网\" → 汇流累积+流域 delineation\n  · \"地形剖面\" → 点击地图生成剖面图\n  · \"点查询\" → 地图上任意点的高程/坡度/坡向/曲率/TPI\n\n🔹 二维水动力模拟\n  · \"进行水动力模拟\" → 自动定位有效DEM区域，LISFLOOD-FP扩散波求解，3D场景动画播放\n  · \"模拟24小时洪水演进\" → Chicago雨型驱动，时间轴逐帧渲染\n  · \"精细三角网\" → 20m间距TIN三角网三维可视化\n  · \"四叉树自适应剖分\" → 地形复杂度自适应网格\n\n🔹 水利工程计算\n  · \"设计暴雨\" → 暴雨强度公式+雨型生成\n  · \"SCS-CN径流\" → 产汇流计算\n  · \"SWMM建模\" → 排水管网模型+模拟\n  · \"排水校核\" → Manning公式管道过流能力\n  · \"洪水预警\" → 实时风险评分+预警等级\n\n🔹 智能交互\n  · 点击地图 → 自动返回完整空间属性\n  · 拖拽工作流 → 自定义编排，自然语言调用\n  · 3D地形查看 → 水位控制+TIN叠加\n\n请描述您的分析需求，或直接点击地图开始。"):
                yield _sse({"type": "text", "content": ch})
            yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000)})
            return

        if not matched and llm_reply:
            yield _sse({"type": "thinking_end", "agent": "router"})
            async for ch in _stream_words(llm_reply):
                yield _sse({"type": "text", "content": ch})
            yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000)})
            return

        agents = ", ".join(sorted({s for s, _, _ in matched}))
        yield _sse({"type": "thinking", "agent": "router", "content": f"匹配 {len(matched)} 个工具 → Agent: [{agents}]"})
        yield _sse({"type": "thinking", "agent": "router", "content": f"执行链: {' → '.join(f'{s}.{t}' for s, t, _ in matched)}"})
        yield _sse({"type": "thinking_end", "agent": "router"})

        yield _sse({"type": "divider", "content": f"⚡ 调度 {len(matched)} 个工具"})

        # === Phase 2: Execute each tool with thinking ===
        async with httpx.AsyncClient(timeout=120.0) as client:
            for i, (server, tool_name, args) in enumerate(matched):
                if tool_name == "__ui_action__":
                    action = args.get("action", "")
                    yield _sse({"type": "ui_action", "action": action, "args": args})
                    action_label = {
                        "open_3d": "🛰️ 已为您打开三维地形查看器",
                        "open_tin": "🔺 已生成TIN三角网叠加到地图",
                        "open_quadtree": "🌳 已生成四叉树自适应剖分叠加到地图",
                    }.get(action, f"UI操作: {action}")
                    yield _sse({"type": "text", "content": action_label})
                    continue

                label = {"gis": "GIS 空间分析专家", "knowledge": "Knowledge 知识管家", "data": "Data 数据工程师", "map": "Map 可视化专家", "hydro": "Hydro 水文建模师", "flood": "Flood 内涝分析师", "raster": "Raster 地形分析专家"}.get(server, server)

                yield _sse({"type": "thinking_start", "agent": server, "label": label})

                steps = THINKING_STEPS.get(server, ["处理中..."])
                step_vars = {"entities": entities, "table": tool_name, "conditions": json.dumps(args.get("conditions", {}), ensure_ascii=False), "params": json.dumps({k: v for k, v in args.items() if k != "geometry"}, ensure_ascii=False), "operation": tool_name, "tool": tool_name}

                for j, step in enumerate(steps):
                    try:
                        formatted = step.format(**{k: v for k, v in step_vars.items() if f"{{{k}}}" in step})
                    except (KeyError, IndexError):
                        formatted = step
                    yield _sse({"type": "thinking", "agent": server, "content": formatted})
                    await asyncio.sleep(0.1 + (0.06 if j < 3 else 0.04))

                yield _sse({"type": "tool_start", "server": server, "tool": tool_name, "step": i + 1, "total": len(matched)})

                url = MCP_SERVERS.get(server, "")
                try:
                    t0 = time.time()
                    resp = await client.post(f"{url}/call_tool", json={"name": tool_name, "arguments": args})
                    ms = int((time.time() - t0) * 1000)
                    result = resp.json()

                    yield _sse({"type": "thinking", "agent": server, "content": f"✅ {tool_name} 返回成功 ({ms}ms)"})
                    yield _sse({"type": "tool_result", "server": server, "tool": tool_name, "result": result, "elapsed_ms": ms})
                    yield _sse({"type": "thinking_end", "agent": server})

                    summary = _format_tool_summary(server, tool_name, result)
                    async for ch in _stream_words(summary):
                        yield _sse({"type": "text", "content": ch})

                except Exception as e:
                    yield _sse({"type": "thinking", "agent": server, "content": f"❌ 失败: {e}"})
                    yield _sse({"type": "thinking_end", "agent": server})
                    yield _sse({"type": "tool_error", "server": server, "tool": tool_name, "error": str(e)})

        total_ms = int((time.time() - t_start) * 1000)
        yield _sse({"type": "event", "agent": "router", "action": "complete", "detail": f"{len(matched)} tools, {total_ms}ms"})
        async for ch in _stream_words(f"\n✅ 全部完成。耗时 {total_ms}ms"):
            yield _sse({"type": "text", "content": ch})
        yield _sse({"type": "done", "duration_ms": total_ms, "tools_called": len(matched)})

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _stream_words(text: str, chunk_size: int = 3):
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]
        await asyncio.sleep(0.02)


async def _stream_simulate_text(text: str, gen_fn):
    pass


def _format_tool_summary(server: str, tool: str, result: dict | list) -> str:
    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        return str(result)

    if tool == "get_parameter":
        entries = result.get("results", [])
        if not entries:
            return f"📋 {result.get('parameter', tool)}: 未找到匹配数据\n"
        lines = [f"📋 {result.get('parameter', tool)} 查询结果：\n"]
        for e in entries[:8]:
            name = e.get("surface", e.get("city", e.get("land_use", "")))
            cond = e.get("condition", e.get("hydrologic_group", ""))
            if tool == "get_parameter" and "n_typical" in e:
                lines.append(f"  • {name} ({cond}): n = {e['n_typical']} [{e.get('n_min','')}, {e.get('n_max','')}]\n")
            elif "A1" in e:
                lines.append(f"  • {name}: q=167×{e['A1']}×(1+{e.get('C','')}×lgP)/({e.get('b','')})^{e.get('n','')}\n")
            elif "cn_amc2" in e:
                lines.append(f"  • {name} ({cond}): CN = {e['cn_amc2']}\n")
            else:
                lines.append(f"  • {json.dumps(e, ensure_ascii=False)[:100]}\n")
        return "".join(lines)

    if tool == "spatial_query":
        return f"🔍 空间查询: relation={result.get('relation')}, result={result.get('result')}\n"

    if tool == "buffer":
        gt = result.get("geometry", {}).get("type", "unknown")
        return f"⭕ 缓冲区生成完成: {gt}\n"

    if tool == "overlay":
        gt = result.get("geometry", {}).get("type", "unknown")
        return f"📐 叠加分析完成: {result.get('operation', '')} → {gt}\n"

    if tool == "geometry_properties":
        return f"📏 几何属性: type={result.get('geometry_type')}, valid={result.get('is_valid')}, bounds={result.get('bounds')}\n"

    if tool == "validate_data":
        return f"✅ 数据验证: valid={result.get('is_valid')}, issues={result.get('issues_found')}\n"

    if tool == "render_map":
        img_len = len(result.get("image_base64", ""))
        return f"🗺️ 地图渲染完成: ~{img_len * 3 // 4 // 1024}KB PNG\n"

    if tool == "design_storm":
        return f"🌧️ 设计暴雨: {result.get('city','')} P={result.get('return_period_years','')}年 历时{result.get('duration_minutes','')}min 峰值{result.get('peak_intensity_mm_per_hr','')}mm/h 总量{result.get('total_depth_mm','')}mm\n"

    if tool == "runoff_compute":
        return f"💧 SCS-CN径流: 降雨{result.get('rainfall_mm','')}mm CN={result.get('curve_number','')} → 径流{result.get('runoff_depth_mm','')}mm 体积{result.get('runoff_volume_m3','')}m³\n"

    if tool == "swmm_create_model":
        return f"🏗️ SWMM模型创建: {result.get('project_name','')} {result.get('n_subcatchments','')}子汇水 {result.get('n_conduits','')}管道\n"

    if tool == "swmm_simulate":
        overflow = result.get('overflow_nodes', [])
        flood_info = f" 溢流节点:{','.join(overflow)}" if overflow else ""
        return f"🔬 SWMM模拟: 峰值流量{result.get('peak_flow_cms','')}cms 最大水深{result.get('max_depth_m','')}m 溢流{result.get('flooding_pct','')}%{flood_info}\n"

    if tool == "flood_assessment":
        return f"🌊 内涝评估: 风险等级[{result.get('risk_level','').upper()}] 平均积水{result.get('avg_flood_depth_cm','')}cm 溢流{result.get('overflow_volume_m3','')}m³\n"

    if tool == "flood_inundation_map":
        return f"🗺️ 淹没范围图: {len(result.get('rings',[]))}级淹没环 总面积{result.get('total_flood_area_m2','')}m²\n"

    if tool == "drainage_assessment":
        status = "✅达标" if result.get('status') == 'adequate' else f"⚠️不足 缺口{result.get('deficit_cms','')}cms"
        return f"🔧 排水能力: 满管流量{result.get('full_flow_capacity_cms','')}cms {status}\n"

    if tool == "flood_warning":
        return f"⚠️ 预警: {result.get('warning_level','').upper()}级 风险分{result.get('risk_score','')} → {', '.join(result.get('recommended_actions',[]))}\n"

    if tool == "flood_risk_zones":
        zones = result.get('zones', [])
        return f"🎯 风险分区: {len(zones)}个区域 人口风险{result.get('total_population_at_risk','')}人\n"

    if tool == "hydrodynamic_2d_sim":
        frames = result.get('frames', [])
        peak = result.get('peak_max_depth_m', '?')
        grid = result.get('grid_size', '?')
        last = frames[-1] if frames else {}
        return f"🌊 2D水动力模拟完成: {len(frames)}帧 | 网格{grid} | 峰值水深{peak}m | 末帧{last.get('flooded_cells',0)}cells\n"

    if tool == "dem_analyze":
        slope = result.get('slope', {})
        return f"⛰️ 地形分析: 坡度均值{slope.get('mean_deg','')}° 优势坡向{result.get('aspect',{}).get('dominant','')} 汇流方向{result.get('flow_direction',{}).get('dominant','')}\n"

    if tool == "watershed_delineate":
        return f"🏞️ 流域提取: 面积{result.get('watershed_area_km2','')}km² 河网密度{result.get('drainage_density','')}km/km²\n"

    if tool == "flow_accumulation":
        return f"🌊 汇流累积: {result.get('n_streams','')}条河流 总长{result.get('total_stream_length_km','')}km\n"

    if tool == "terrain_profile":
        return f"📈 地形剖面: 长{result.get('total_distance_m','')}m 高差{round(result.get('max_elevation_m',0)-result.get('min_elevation_m',0),1)}m\n"

    if tool == "calibrate_suggest":
        return f"🔧 率定建议: NSE={result.get('nash_sutcliffe','')}({result.get('nse_rating','')}) 峰值误差{result.get('error_pct','')}% → {len(result.get('suggestions',[]))}条建议\n"

    if "error" in result:
        return f"❌ 错误: {result['error']}\n"

    return f"⚙️ {server}.{tool}: {json.dumps(result, ensure_ascii=False)[:200]}\n"


def _pick_knowledge_tool(msg: str) -> tuple[str, dict]:
    if "糙率" in msg or "manning" in msg.lower():
        surface = "混凝土管道"
        for kw, val in [("HDPE","HDPE"),("hdpe","HDPE"),("塑料","HDPE"),("砖","砖砌"),("河道","天然河道"),("沥青","沥青")]:
            if kw in msg: surface = val
        return "get_parameter", {"parameter_name": "manning_n", "conditions": {"surface": surface}}
    if "暴雨" in msg or "重现期" in msg or "公式" in msg:
        city = "北京"
        for c in ["上海","广州","深圳","成都","武汉","南京","杭州","重庆","天津"]:
            if c in msg: city = c
        return "get_parameter", {"parameter_name": "design_storm", "conditions": {"city": city}}
    if "CN" in msg or "曲线" in msg or "产流" in msg:
        return "get_parameter", {"parameter_name": "scs_cn", "conditions": {}}
    return "search", {"query": msg}


def _pick_gis_tool(msg: str) -> tuple[str, dict]:
    if "导入" in msg or "上传" in msg or "管网" in msg and "数据" in msg:
        import re
        m = re.search(r'[\w-]+\.(geojson|json|shp|gpkg|kml)', msg, re.IGNORECASE)
        fname = m.group(0) if m else ""
        return "import_network", {"file_name": fname}
    if "缓冲" in msg:
        return "buffer", {"geometry": {"type": "Point", "coordinates": [116.397, 39.908]}, "distance": 0.05}
    if "叠加" in msg or "交集" in msg:
        return "overlay", {"geometry_a": {"type": "Polygon", "coordinates": [[[0,0],[2,0],[2,2],[0,2],[0,0]]]}, "geometry_b": {"type": "Polygon", "coordinates": [[[1,0],[3,0],[3,2],[1,2],[1,0]]]}, "operation": "intersection"}
    if "属性" in msg or "面积" in msg:
        return "geometry_properties", {"geometry": {"type": "Polygon", "coordinates": [[[116.3,39.9],[116.4,39.9],[116.4,40.0],[116.3,40.0],[116.3,39.9]]]}}
    return "spatial_query", {"geometry_a": {"type": "Polygon", "coordinates": [[[116.2,39.7],[116.6,39.7],[116.6,40.1],[116.2,40.1],[116.2,39.7]]]}, "geometry_b": {"type": "Point", "coordinates": [116.397, 39.908]}, "relation": "contains"}


def _pick_data_tool(msg: str) -> tuple[str, dict]:
    return "list_tables", {}


def _pick_map_tool(msg: str) -> tuple[str, dict]:
    return "render_map", {"layers": [{"data": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[116.3,39.9],[116.4,39.9],[116.4,40.0],[116.3,40.0],[116.3,39.9]]]}, "properties": {}}]}, "style": {"color": "#00d4ff", "alpha": 0.3}}], "title": "S-AI Analysis"}


def _pick_hydro_tool(msg: str) -> tuple[str, dict]:
    if "雨型" in msg or "暴雨强度" in msg or "设计暴雨" in msg:
        city = "beijing"
        for c, e in [("北京","beijing"),("上海","shanghai"),("深圳","shenzhen"),("广州","guangzhou"),("成都","chengdu")]:
            if c in msg: city = e
        return "design_storm", {"city": city, "return_period": 50, "duration_minutes": 120}
    if "径流" in msg or "产流" in msg or "SCS" in msg or "CN" in msg:
        return "runoff_compute", {"rainfall_mm": 80, "curve_number": 75, "drainage_area_ha": 10}
    if "swmm" in msg.lower() or "SWMM" in msg or "模型" in msg:
        return "swmm_create_model", {"project_name": "sai_demo", "area_hectares": 10, "impervious_percent": 60}
    if "模拟" in msg or "仿真" in msg:
        return "swmm_simulate", {"rainfall_mm_hr": 80, "duration_min": 120}
    if "洪峰" in msg or "调参" in msg or "率定" in msg or "校准" in msg:
        return "calibrate_suggest", {"observed_peak_flow": 1.5, "simulated_peak_flow": 2.0, "nash_sutcliffe": 0.65}
    return "runoff_compute", {"rainfall_mm": 80, "curve_number": 75, "drainage_area_ha": 10}


def _pick_flood_tool(msg: str) -> tuple[str, dict]:
    if "预警" in msg:
        return "flood_warning", {"current_rainfall_mm_hr": 60, "forecast_rainfall_mm_hr": 80, "soil_saturation_pct": 70, "drainage_utilization_pct": 85}
    if "排水" in msg or "管网" in msg or "管径" in msg:
        return "drainage_assessment", {"pipe_diameter_m": 0.8, "pipe_slope": 0.003, "design_flow_cms": 1.5}
    if "风险区" in msg:
        return "flood_risk_zones", {}
    hydro2d_kw = ("水动力", "二维模拟", "演进", "淹没过程", "淹没演进", "洪水演进", "动态模拟", "洪泛", "水动力模拟")
    if any(k in msg for k in hydro2d_kw):
        import re
        hours = 24
        m = re.search(r'(\d+)\s*小时', msg)
        if m:
            hours = int(m.group(1))
        rm = re.search(r'(\d+)\s*mm', msg)
        rain_mm = float(rm.group(1)) if rm else 120.0
        return "hydrodynamic_2d_sim", {"duration_hr": hours, "output_steps": 12, "rain_pattern": "chicago", "rainfall_mm": rain_mm}
    import re
    m = re.search(r'水位\s*(\d+\.?\d*)', msg)
    wl = float(m.group(1)) if m else None
    inundation_args = {"radius_m": 2000, "max_depth_m": 2.0}
    if wl:
        inundation_args["water_level_m"] = wl
    return "flood_inundation_map", inundation_args


def _pick_raster_tool(msg: str) -> tuple[str, dict]:
    if any(k in msg for k in ["三角网", "TIN", "不规则三角"]):
        return "__ui_action__", {"action": "open_tin"}
    if any(k in msg for k in ["四叉树", "Quadtree", "自适应剖分", "嵌套细分"]):
        return "__ui_action__", {"action": "open_quadtree"}
    if any(k in msg for k in ["三维", "3D", "立体", "高度场", "heightmap", "立体场景", "三维场景"]):
        return "__ui_action__", {"action": "open_3d"}
    if any(k in msg for k in ["点查询", "空间情报", "空间属性", "点击查询", "此点信息"]):
        return "point_query", {}
    if "渲染" in msg or "等高线" in msg or "阴影" in msg or "hillshade" in msg.lower():
        return "dem_render", {}
    if "坡度" in msg or "坡向" in msg or "地形" in msg:
        return "dem_analyze", {"compute_slope": True, "compute_aspect": True}
    if "汇流" in msg and ("累积" in msg or "分析" in msg):
        return "flow_accumulation", {}
    if "流域" in msg or "汇水" in msg:
        return "watershed_delineate", {}
    if "河网" in msg or "河流" in msg or "水系" in msg:
        return "flow_accumulation", {}
    if "剖面" in msg or "断面" in msg:
        return "terrain_profile", {}
    return "dem_analyze", {}


def _keyword_fallback(msg: str) -> list[tuple[str, str, dict]]:
    raster_kw = {"坡度", "坡向", "地形", "DEM", "dem", "汇流", "流域", "汇水", "剖面", "断面", "等高线", "河网", "河流", "水系", "渲染", "阴影", "hillshade"}
    flood_kw = {"内涝", "淹没", "洪水", "积水", "预警", "排水", "风险区", "风险", "水动力", "淹没过程", "淹没演进", "洪水演进", "动态模拟", "洪泛", "二维模拟"}
    hydro_kw = {"暴雨", "雨型", "产流", "径流", "SWMM", "swmm", "模型", "模拟", "洪峰", "调参", "率定", "校准"}
    knowledge_kw = {"糙率", "manning", "曼宁", "CN", "曲线数", "管径", "DN", "HDPE", "设计标准", "重现期", "水泵", "LID", "海绵", "透水"}
    gis_kw = {"导入", "上传", "缓冲", "叠加", "交集", "几何", "空间"}
    ui_kw = {"3D", "三维", "立体", "heightmap", "三角网", "TIN", "不规则三角", "四叉树", "Quadtree", "嵌套剖分", "自适应剖分"}

    matched = []
    if any(k in msg for k in ui_kw):
        tool, args = _pick_raster_tool(msg)
        if tool == "__ui_action__":
            matched.append(("ui", "__ui_action__", args))
            return matched
    if any(k in msg for k in raster_kw):
        tool, args = _pick_raster_tool(msg)
        matched.append(("raster", tool, args))
    if any(k in msg for k in flood_kw):
        tool, args = _pick_flood_tool(msg)
        matched.append(("flood", tool, args))
    hydro2d_active = any(t == "hydrodynamic_2d_sim" for _, t, _ in matched)
    if any(k in msg for k in hydro_kw) and not hydro2d_active:
        tool, args = _pick_hydro_tool(msg)
        matched.append(("hydro", tool, args))
    if any(k in msg for k in knowledge_kw):
        matched.append(("knowledge", "get_parameter", {"parameter_name": _extract_param_name(msg)}))
    if any(k in msg for k in gis_kw):
        tool, args = _pick_gis_tool(msg)
        matched.append(("gis", tool, args))

    seen = set()
    deduped = []
    for s, t, a in matched:
        key = f"{s}.{t}"
        if key not in seen:
            seen.add(key)
            deduped.append((s, t, a))
    return deduped


def _extract_param_name(msg: str) -> str:
    if any(k in msg for k in ("糙率", "manning", "曼宁")):
        return "manning_n"
    if any(k in msg for k in ("CN", "曲线数")):
        return "scs_cn"
    if any(k in msg for k in ("管径", "DN", "HDPE", "混凝土管", "铸铁")):
        return "pipe_specs"
    if any(k in msg for k in ("水泵", "泵站")):
        return "pump_specs"
    if any(k in msg for k in ("设计标准", "重现期", "径流系数")):
        return "drainage_design"
    if any(k in msg for k in ("LID", "海绵", "透水")):
        return "lid_design"
    if "暴雨" in msg or "雨型" in msg:
        return "design_storm"
    return "manning_n"


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
