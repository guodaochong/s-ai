from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import structlog
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

load_dotenv(Path(__file__).parent.parent / ".env")

logger = structlog.get_logger(__name__)

ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")
GLM_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

MODEL_FLASH = "glm-4-flash-250414"
MODEL_AIR = "glm-4-air-250414"

CACHE_MAX = 200
CACHE_TTL = 300
MAX_CONTEXT_CHARS = 4000
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 120

_tool_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_circuit_breaker: dict[str, tuple[int, float]] = {}
_last_cache_sweep = time.time()

MCP_SERVERS = {
    "knowledge": "http://127.0.0.1:5003",
    "gis": "http://127.0.0.1:5001",
    "data": "http://127.0.0.1:5002",
    "map": "http://127.0.0.1:5004",
    "hydro": "http://127.0.0.1:5005",
    "flood": "http://127.0.0.1:5006",
    "raster": "http://127.0.0.1:5007",
}

MAX_REACT_STEPS = 8

AGENT_LABELS = {
    "gis": "GIS 空间分析", "knowledge": "Knowledge 知识查询", "data": "Data 数据操作",
    "map": "Map 地图渲染", "hydro": "Hydro 水文计算", "flood": "Flood 洪水分析",
    "raster": "Raster 地形分析",
}

GLM_TOOLS = [
    {"type": "function", "function": {"name": "get_parameter", "description": "查询水利参数表(manning_n糙率/scs_cn曲线数/design_storm暴雨/pipe_specs管材/pump_specs水泵/lid_design海绵/drainage_design排水标准)", "parameters": {"type": "object", "properties": {"parameter_name": {"type": "string", "description": "参数表名: manning_n, scs_cn, design_storm, pipe_specs, pump_specs, lid_design, drainage_design"}, "conditions": {"type": "object", "description": "过滤条件, 如 {\"surface\": \"混凝土管道\"} 或 {\"city\": \"成都\"}", "properties": {}}}, "required": ["parameter_name"]}}},
    {"type": "function", "function": {"name": "search", "description": "知识库语义搜索", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_standard", "description": "查询水利标准规范", "parameters": {"type": "object", "properties": {"standard_id": {"type": "string", "description": "标准编号如 GB50014"}, "keyword": {"type": "string", "description": "关键词搜索"}}, "required": ["standard_id"]}}},
    {"type": "function", "function": {"name": "explain_concept", "description": "解释水利专业概念(水文/水力/排水/防洪)", "parameters": {"type": "object", "properties": {"concept": {"type": "string", "description": "概念名称, 如'曼宁公式'、'SCS-CN'、'设计暴雨'"}, "detail_level": {"type": "string", "enum": ["brief", "detailed", "technical"], "description": "详细程度", "default": "detailed"}}, "required": ["concept"]}}},
    {"type": "function", "function": {"name": "spatial_query", "description": "空间关系查询(intersects/contains/within/touches/crosses等)", "parameters": {"type": "object", "properties": {"geometry_a": {"type": "object", "description": "GeoJSON geometry"}, "geometry_b": {"type": "object", "description": "GeoJSON geometry"}, "relation": {"type": "string", "enum": ["intersects", "contains", "within", "touches", "crosses", "overlaps", "equals", "disjoint"], "default": "intersects"}}, "required": ["geometry_a", "geometry_b"]}}},
    {"type": "function", "function": {"name": "buffer", "description": "创建几何缓冲区", "parameters": {"type": "object", "properties": {"geometry": {"type": "object", "description": "GeoJSON geometry"}, "distance": {"type": "number", "description": "缓冲距离(米)"}, "unit": {"type": "string", "default": "meters"}}, "required": ["geometry"]}}},
    {"type": "function", "function": {"name": "overlay", "description": "叠加分析(intersection/union/difference/symmetric_difference)", "parameters": {"type": "object", "properties": {"geometry_a": {"type": "object", "description": "GeoJSON geometry"}, "geometry_b": {"type": "object", "description": "GeoJSON geometry"}, "operation": {"type": "string", "enum": ["intersection", "union", "difference", "symmetric_difference"], "default": "intersection"}}, "required": ["geometry_a", "geometry_b"]}}},
    {"type": "function", "function": {"name": "coordinate_transform", "description": "坐标系转换(WGS84↔CGCS2000等)", "parameters": {"type": "object", "properties": {"geometry": {"type": "object", "description": "GeoJSON geometry"}, "source_crs": {"type": "integer", "description": "源EPSG代码"}, "target_crs": {"type": "integer", "description": "目标EPSG代码"}}, "required": ["geometry", "source_crs", "target_crs"]}}},
    {"type": "function", "function": {"name": "geometry_properties", "description": "几何属性计算(面积/周长/质心/类型)", "parameters": {"type": "object", "properties": {"geometry": {"type": "object", "description": "GeoJSON geometry"}}, "required": ["geometry"]}}},
    {"type": "function", "function": {"name": "import_network", "description": "导入管网/河网矢量数据", "parameters": {"type": "object", "properties": {"file_name": {"type": "string", "description": "文件名"}}, "required": ["file_name"]}}},
    {"type": "function", "function": {"name": "import_data", "description": "导入空间数据(GeoJSON)到数据库", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "GeoJSON FeatureCollection"}, "table_name": {"type": "string", "description": "目标表名"}}, "required": ["data", "table_name"]}}},
    {"type": "function", "function": {"name": "validate_data", "description": "数据质量验证(拓扑/属性/坐标系)", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "GeoJSON数据"}, "checks": {"type": "array", "items": {"type": "string"}, "description": "检查项: topology, attributes, crs"}}, "required": ["data"]}}},
    {"type": "function", "function": {"name": "render_map", "description": "渲染静态地图图像(PNG)", "parameters": {"type": "object", "properties": {"layers": {"type": "array", "items": {"type": "object"}, "description": "图层数据列表"}, "title": {"type": "string", "description": "地图标题"}}, "required": ["layers"]}}},
    {"type": "function", "function": {"name": "design_storm", "description": "生成设计暴雨雨型(Chicago时程分布)", "parameters": {"type": "object", "properties": {"city": {"type": "string", "enum": ["beijing", "shanghai", "shenzhen", "guangzhou", "chengdu"], "description": "城市"}, "return_period": {"type": "integer", "description": "重现期(年), 如50年一遇=50"}, "duration_minutes": {"type": "integer", "description": "降雨历时(分钟)"}, "time_step_minutes": {"type": "integer", "description": "时间步长(分钟)", "default": 5}}, "required": ["city", "return_period"]}}},
    {"type": "function", "function": {"name": "runoff_compute", "description": "SCS-CN法径流计算", "parameters": {"type": "object", "properties": {"rainfall_mm": {"type": "number", "description": "降雨量(毫米)"}, "curve_number": {"type": "integer", "description": "SCS曲线数CN值(城市50-70/郊区30-50/农田20-40)"}, "drainage_area_ha": {"type": "number", "description": "汇水面积(公顷)"}}, "required": ["rainfall_mm", "curve_number", "drainage_area_ha"]}}},
    {"type": "function", "function": {"name": "swmm_create_model", "description": "创建EPA SWMM排水管网模型", "parameters": {"type": "object", "properties": {"project_name": {"type": "string", "description": "项目名称"}, "area_hectares": {"type": "number", "description": "面积(公顷)"}, "impervious_percent": {"type": "number", "description": "不透水面积百分比(0-100)"}, "n_subcatchments": {"type": "integer", "description": "子汇水区数量"}}, "required": ["project_name", "area_hectares"]}}},
    {"type": "function", "function": {"name": "swmm_simulate", "description": "运行SWMM排水模拟", "parameters": {"type": "object", "properties": {"project_name": {"type": "string", "description": "项目名称"}, "rainfall_mm_hr": {"type": "number", "description": "降雨强度(mm/h)"}, "duration_min": {"type": "integer", "description": "模拟时长(分钟)"}}, "required": ["rainfall_mm_hr", "duration_min"]}}},
    {"type": "function", "function": {"name": "calibrate_suggest", "description": "模型率定建议(NSE/RMSE/参数调整)", "parameters": {"type": "object", "properties": {"observed_peak_flow": {"type": "number", "description": "实测洪峰流量(m³/s)"}, "simulated_peak_flow": {"type": "number", "description": "模拟洪峰流量(m³/s)"}, "nash_sutcliffe": {"type": "number", "description": "Nash-Sutcliffe效率系数"}}, "required": ["observed_peak_flow", "simulated_peak_flow", "nash_sutcliffe"]}}},
    {"type": "function", "function": {"name": "flood_inundation_map", "description": "生成洪水淹没范围图(GeoJSON渲染到地图). DEM在甘肃迭部(104.89°E,33.19°N), 无需传坐标会自动定位", "parameters": {"type": "object", "properties": {"radius_m": {"type": "number", "description": "淹没分析半径(米)", "default": 2000}, "max_depth_m": {"type": "number", "description": "最大水深(米)", "default": 2.0}, "water_level_m": {"type": "number", "description": "指定水位(米, 可选)"}, "rainfall_mm": {"type": "number", "description": "降雨量(毫米)"}}, "required": []}}},
    {"type": "function", "function": {"name": "flood_assessment", "description": "城市内涝风险评估(数值计算)", "parameters": {"type": "object", "properties": {"rainfall_mm": {"type": "number", "description": "降雨量(毫米)"}, "drainage_area_ha": {"type": "number", "description": "汇水面积(公顷)"}, "impervious_pct": {"type": "number", "description": "不透水面积比例(0-100)"}, "pipe_capacity_cms": {"type": "number", "description": "管道排水能力(m³/s)"}}, "required": ["rainfall_mm", "drainage_area_ha"]}}},
    {"type": "function", "function": {"name": "drainage_assessment", "description": "排水管道能力校核(Manning公式)", "parameters": {"type": "object", "properties": {"pipe_diameter_m": {"type": "number", "description": "管径(米)"}, "pipe_slope": {"type": "number", "description": "管道坡度"}, "manning_n": {"type": "number", "description": "曼宁糙率(0.01-0.03)"}, "design_flow_cms": {"type": "number", "description": "设计流量(m³/s)"}}, "required": ["pipe_diameter_m", "pipe_slope"]}}},
    {"type": "function", "function": {"name": "flood_warning", "description": "洪水预警评估(风险等级+建议措施)", "parameters": {"type": "object", "properties": {"current_rainfall_mm_hr": {"type": "number", "description": "当前降雨强度(mm/h)"}, "forecast_rainfall_mm_hr": {"type": "number", "description": "预报降雨强度(mm/h)"}, "soil_saturation_pct": {"type": "number", "description": "土壤饱和度(0-100)"}, "drainage_utilization_pct": {"type": "number", "description": "排水设施利用率(0-100)"}}, "required": ["current_rainfall_mm_hr"]}}},
    {"type": "function", "function": {"name": "flood_risk_zones", "description": "洪水风险分区(按人口/基础设施密度)", "parameters": {"type": "object", "properties": {"population_density": {"type": "number", "description": "人口密度(人/km²)"}, "infrastructure_density": {"type": "number", "description": "基础设施密度(0-1)"}}, "required": []}}},
    {"type": "function", "function": {"name": "hydrodynamic_2d_sim", "description": "二维水动力淹没演进模拟(LISFLOOD-FP扩散波求解器, 基于真实0.5m DEM, 结果可在3D场景播放动画)", "parameters": {"type": "object", "properties": {"duration_hr": {"type": "integer", "description": "模拟时长(小时)", "default": 24}, "output_steps": {"type": "integer", "description": "输出帧数", "default": 12}, "rain_pattern": {"type": "string", "enum": ["chicago", "uniform"], "description": "雨型", "default": "chicago"}, "rainfall_mm": {"type": "number", "description": "总降雨量(毫米)", "default": 120}}, "required": []}}},
    {"type": "function", "function": {"name": "dem_analyze", "description": "DEM地形分析(坡度/坡向/汇流方向统计)", "parameters": {"type": "object", "properties": {"compute_slope": {"type": "boolean", "description": "计算坡度", "default": True}, "compute_aspect": {"type": "boolean", "description": "计算坡向", "default": True}, "compute_flowdir": {"type": "boolean", "description": "计算汇流方向", "default": True}}, "required": []}}},
    {"type": "function", "function": {"name": "watershed_delineate", "description": "流域提取与河网分析(D8算法, 面积/密度/分级)", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "flow_accumulation", "description": "汇流累积计算与河网自动提取(Strahler分级)", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "terrain_profile", "description": "地形剖面线分析(两点间高程变化)", "parameters": {"type": "object", "properties": {"start_lng": {"type": "number", "description": "起点经度"}, "start_lat": {"type": "number", "description": "起点纬度"}, "end_lng": {"type": "number", "description": "终点经度"}, "end_lat": {"type": "number", "description": "终点纬度"}}, "required": ["start_lng", "start_lat", "end_lng", "end_lat"]}}},
    {"type": "function", "function": {"name": "point_query", "description": "地图点位查询(高程/坡度/坡向/曲率/TPI)", "parameters": {"type": "object", "properties": {"lng": {"type": "number", "description": "经度"}, "lat": {"type": "number", "description": "纬度"}}, "required": ["lng", "lat"]}}},
    {"type": "function", "function": {"name": "dem_render", "description": "DEM渲染(等高线/阴影浮雕图)", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "tin_generate", "description": "生成TIN不规则三角网(三维地形网格)", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "quadtree_subdivide", "description": "四叉树自适应地形剖分", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "create_choropleth", "description": "创建专题地图(分类着色)", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "数据GeoJSON"}, "value_field": {"type": "string", "description": "数值字段名"}, "colormap": {"type": "string", "description": "配色方案", "default": "YlOrRd"}}, "required": ["data", "value_field"]}}},
    {"type": "function", "function": {"name": "plot_timeseries", "description": "绘制时间序列图表(降雨/水位/流量过程线)", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "时序数据"}, "title": {"type": "string", "description": "图表标题"}}, "required": ["data"]}}},
    {"type": "function", "function": {"name": "query_spatial", "description": "空间SQL查询(PostGIS只读)", "parameters": {"type": "object", "properties": {"sql": {"type": "string", "description": "SQL查询语句(仅SELECT)"}}, "required": ["sql"]}}},
    {"type": "function", "function": {"name": "export_geojson", "description": "导出GeoJSON数据文件", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "GeoJSON数据"}, "filename": {"type": "string", "description": "文件名"}}, "required": ["data"]}}},
]

TOOL_TO_SERVER = {}
for _srv, _tools in {
    "knowledge": ["get_parameter", "search", "get_standard", "explain_concept"],
    "gis": ["spatial_query", "buffer", "overlay", "coordinate_transform", "geometry_properties", "read_vector", "write_vector", "import_network"],
    "data": ["import_data", "query_spatial", "query_by_geometry", "validate_data", "list_tables"],
    "map": ["render_map", "create_choropleth", "plot_timeseries", "export_geojson"],
    "hydro": ["design_storm", "runoff_compute", "swmm_create_model", "swmm_simulate", "calibrate_suggest"],
    "flood": ["flood_inundation_map", "flood_assessment", "drainage_assessment", "flood_warning", "flood_risk_zones", "hydrodynamic_2d_sim"],
    "raster": ["dem_analyze", "watershed_delineate", "flow_accumulation", "terrain_profile", "point_query", "dem_render", "tin_generate", "quadtree_subdivide"],
}.items():
    for _t in _tools:
        TOOL_TO_SERVER[_t] = _srv

REACT_SYSTEM_PROMPT = """你是 S-AI 水利空间智能体，具备自主推理能力。专业水利工程师和空间分析师。

DEM数据位于甘肃迭部县(104.89°E, 33.19°N)，0.5m分辨率，3GB GeoTIFF。

必须调工具的场景（不要直接回复文字，必须调工具）：
- 进行/运行/执行 模拟、计算、分析 → 调对应工具
- 查/查询 参数、数值 → 调 get_parameter
- 涉及具体数值 → 必须调工具，不要捏造
- 用户提到内涝/淹没/洪水/积水 → 必须调 flood_inundation_map

可以不调工具的场景：
- 纯寒暄（你好/谢谢/再见）

推理规则：
- 复合任务需多步推理：先获取参数→再计算→最后评估
- 参数从对话上下文提取实际值，不要编造
- 工具返回错误时分析原因并调整参数重试
- 回复专业、准确、有条理"""


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _detect_ui_action(msg: str) -> str:
    if any(k in msg for k in ["三角网", "TIN", "不规则三角"]):
        return "open_tin"
    if any(k in msg for k in ["四叉树", "Quadtree", "嵌套剖分", "自适应剖分"]):
        return "open_quadtree"
    if any(k in msg for k in ["三维", "3D", "立体", "heightmap", "立体场景", "三维场景", "立体地形", "三维地形"]):
        return "open_3d"
    return ""


def _compress_result(tool: str, result: dict) -> str:
    if "error" in result:
        return f"ERROR: {result['error']}"
    if tool == "design_storm":
        return f"暴雨: P={result.get('return_period_years','?')}年 峰值={result.get('peak_intensity_mm_per_hr','?')}mm/h 总量={result.get('total_depth_mm','?')}mm"
    if tool == "runoff_compute":
        return f"径流: 降雨{result.get('rainfall_mm','?')}mm CN={result.get('curve_number','?')} → 径流{result.get('runoff_depth_mm','?')}mm 体积{result.get('runoff_volume_m3','?')}m³"
    if tool == "hydrodynamic_2d_sim":
        return f"2D模拟: {len(result.get('frames',[]))}帧 峰值水深={result.get('peak_max_depth_m','?')}m 网格={result.get('grid_size','?')}"
    if tool == "flood_assessment":
        return f"内涝: 风险={result.get('risk_level','?')} 积水={result.get('avg_flood_depth_cm','?')}cm 溢流={result.get('overflow_volume_m3','?')}m³"
    if tool == "flood_inundation_map":
        return f"淹没: {len(result.get('rings',[]))}级 面积={result.get('total_flood_area_m2','?')}m²"
    if tool == "dem_analyze":
        s = result.get('slope', {})
        return f"地形: 坡度{s.get('mean_deg','?')}° 坡向={result.get('aspect',{}).get('dominant','?')}"
    if tool == "watershed_delineate":
        return f"流域: {result.get('watershed_area_km2','?')}km² 密度={result.get('drainage_density','?')}km/km²"
    if tool == "flow_accumulation":
        return f"河网: {result.get('n_streams','?')}条 总长{result.get('total_stream_length_km','?')}km"
    if tool == "drainage_assessment":
        return f"排水: 满管{result.get('full_flow_capacity_cms','?')}cms {'达标' if result.get('status')=='adequate' else '不足'}"
    if tool == "flood_warning":
        return f"预警: {result.get('warning_level','?')}级 风险={result.get('risk_score','?')}"
    if tool == "get_parameter":
        entries = result.get("results", [])
        return f"参数({result.get('parameter','?')}): {len(entries)}条 " + "; ".join(json.dumps(e, ensure_ascii=False)[:80] for e in entries[:3])
    if tool == "swmm_simulate":
        return f"SWMM: 峰值{result.get('peak_flow_cms','?')}cms 水深{result.get('max_depth_m','?')}m 溢流{result.get('flooding_pct','?')}%"
    if tool == "calibrate_suggest":
        return f"率定: NSE={result.get('nash_sutcliffe','?')} 误差{result.get('error_pct','?')}%"
    if tool == "point_query":
        return f"点位: 高程={result.get('elevation_m','?')}m 坡度={result.get('slope_deg','?')}°"
    if tool == "terrain_profile":
        return f"剖面: 长{result.get('total_distance_m','?')}m 高差{round(result.get('max_elevation_m',0)-result.get('min_elevation_m',0),1)}m"
    return json.dumps(result, ensure_ascii=False)[:200]


async def _call_llm(messages: list[dict], model: str = MODEL_FLASH, use_tools: bool = True) -> tuple[str, str, list[dict]]:
    headers = {"Authorization": f"Bearer {ZHIPUAI_API_KEY}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 1024,
    }
    if use_tools and GLM_TOOLS:
        payload["tools"] = GLM_TOOLS
        payload["tool_choice"] = "auto"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(GLM_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content", "") or ""
        reasoning = msg.get("reasoning_content", "") or ""
        tool_calls = msg.get("tool_calls") or []
        return content, reasoning, tool_calls


SIMPLE_KEYWORDS = {"你好", "谢谢", "再见", "hello", "hi", "拜拜", "早上好", "晚上好", "谢谢啦", "哈喽"}

ROUTING_RULES: list[tuple[str, str]] = [
    (r"水动力|淹没模拟|洪水模拟|二维模拟|洪水演进", "hydrodynamic_2d_sim"),
    (r"什么是|解释|介绍.*概念|原理是|怎么理解|什么是.*公式", "explain_concept"),
    (r"糙率|曲线数|CN值|管材|水泵|海绵|排水标准|暴雨参数", "get_parameter"),
    (r"河网|水流累积|汇流", "flow_accumulation"),
    (r"流域|汇水|子流域", "watershed_delineate"),
    (r"高程|坡度|查点|点位查询", "point_query"),
    (r"剖面|断面", "terrain_profile"),
    (r"地形分析|DEM分析|地形特征", "dem_analyze"),
    (r"TIN|三角网|不规则三角", "tin_generate"),
    (r"四叉树|自适应剖分|嵌套剖分", "quadtree_subdivide"),
    (r"暴雨雨型|设计暴雨|暴雨强度", "design_storm"),
    (r"径流|产流|汇流量", "runoff_compute"),
    (r"淹没范围|淹没地图|淹没面积|淹没图|会不会被水淹|积水", "flood_inundation_map"),
    (r"洪水风险|内涝评估|风险评估", "flood_assessment"),
    (r"排水能力|排水评估|排水系统", "drainage_assessment"),
    (r"洪水预警|预警|防汛预警", "flood_warning"),
    (r"风险分区|风险等级|风险区域", "flood_risk_zones"),
    (r"渲染|出图|画图|绘制地图", "render_map"),
    (r"管网|SWMM|swmm|排水管网", "swmm_simulate"),
    (r"空间关系|相交|包含|相邻|空间查询", "spatial_query"),
    (r"缓冲区|缓冲|周边范围", "buffer"),
    (r"叠加|交集|并集|差集|叠加分析", "overlay"),
    (r"坐标转换|坐标系转换", "coordinate_transform"),
    (r"搜索|查找资料|知识库", "search"),
    (r"标准|规范|GB|SL|设计规范", "get_standard"),
    (r"率定|校准|参数优化", "calibrate_suggest"),
    (r"河网渲染|DEM渲染|地形渲染", "dem_render"),
    (r"模拟|计算|运行.*分析|进行.*分析|开启.*计算", "hydrodynamic_2d_sim"),
]

TOOL_CORPUS = [
    ("查询水利参数 糙率 曲线数 暴雨参数 管材 水泵 海绵 排水标准", "get_parameter"),
    ("知识库语义搜索 查找资料", "search"),
    ("查询水利标准规范 GB SL", "get_standard"),
    ("解释水利专业概念 水文 水力 排水 防洪 曼宁公式 原理", "explain_concept"),
    ("空间关系查询 相交 包含 穿越 触碰", "spatial_query"),
    ("创建几何缓冲区 周边范围", "buffer"),
    ("叠加分析 交集 并集 差集", "overlay"),
    ("坐标系转换 EPSG WGS84 CGCS2000", "coordinate_transform"),
    ("几何属性 面积 周长 类型", "geometry_properties"),
    ("数据验证 完整性检查", "validate_data"),
    ("地图渲染 出图 绘制", "render_map"),
    ("生成设计暴雨雨型 暴雨强度 历时", "design_storm"),
    ("计算径流量 产流 SCS-CN", "runoff_compute"),
    ("创建SWMM管网模型 子汇水", "swmm_create_model"),
    ("运行SWMM管网模拟 排水管网", "swmm_simulate"),
    ("模型率定校准 NSE 参数优化", "calibrate_suggest"),
    ("渲染洪水淹没范围图 淹没面积 会不会被水淹 积水", "flood_inundation_map"),
    ("洪水风险评估 内涝评估 积水", "flood_assessment"),
    ("排水系统能力评估 排水评估", "drainage_assessment"),
    ("洪水预警 水位预警 防汛", "flood_warning"),
    ("洪水风险区域划分 风险等级", "flood_risk_zones"),
    ("二维水动力淹没模拟 洪水演进 水深", "hydrodynamic_2d_sim"),
    ("DEM地形分析 坡度 坡向 高程统计", "dem_analyze"),
    ("流域划分 提取流域 子流域", "watershed_delineate"),
    ("河网提取 水流累积 汇流 河道", "flow_accumulation"),
    ("地形剖面 断面 高程变化", "terrain_profile"),
    ("点位查询 高程 坐标查询", "point_query"),
    ("DEM渲染 地形渲染", "dem_render"),
    ("生成TIN不规则三角网 三角化", "tin_generate"),
    ("四叉树自适应剖分 网格划分", "quadtree_subdivide"),
    ("降雨径流关系 降雨和径流的关系 产汇流", "runoff_compute"),
    ("被水淹没 水淹 淹水 洪涝 涝灾", "flood_inundation_map"),
    ("区域分析 区域怎么样 区域评估 区域情况", "flood_assessment"),
]

_tfidf_vec: TfidfVectorizer | None = None
_tfidf_matrix: np.ndarray | None = None
_tfidf_tool_names: list[str] = []


def _init_tfidf():
    global _tfidf_vec, _tfidf_matrix, _tfidf_tool_names
    if _tfidf_vec is not None:
        return
    _tfidf_tool_names = [t for _, t in TOOL_CORPUS]
    corpus = [d for d, _ in TOOL_CORPUS]
    _tfidf_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
    _tfidf_matrix = _tfidf_vec.fit_transform(corpus)


def _semantic_route(query: str) -> str | None:
    _init_tfidf()
    if _tfidf_matrix is None:
        return None
    q_vec = _tfidf_vec.transform([query])
    scores = cosine_similarity(q_vec, _tfidf_matrix)[0]
    best_idx = int(np.argmax(scores))
    if scores[best_idx] < 0.15:
        return None
    return _tfidf_tool_names[best_idx]


async def _route(message: str, history: list[dict]) -> str:
    if any(kw in message.lower() for kw in SIMPLE_KEYWORDS):
        return "SIMPLE"

    for pattern, tool in ROUTING_RULES:
        if re.search(pattern, message):
            return f"DIRECT:{tool}"

    sem_hit = _semantic_route(message)
    if sem_hit:
        return f"DIRECT:{sem_hit}"

    plan_prompt = """你是水利空间智能体的规划模块。根据用户意图选择执行模式：

模式A - 仅寒暄闲聊 → 回复 "SIMPLE"
模式B - 单工具任务 → 回复 "DIRECT: 工具名"
模式C - 多步流水线 → 列出步骤

优先选择模式B。只有明确需要多个工具协同才选模式C。
可用工具：hydrodynamic_2d_sim, get_parameter, explain_concept, search, get_standard, dem_analyze, watershed_delineate, flow_accumulation, terrain_profile, point_query, dem_render, tin_generate, quadtree_subdivide, design_storm, runoff_compute, swmm_create_model, swmm_simulate, calibrate_suggest, flood_inundation_map, flood_assessment, drainage_assessment, flood_warning, flood_risk_zones, spatial_query, buffer, overlay, coordinate_transform, geometry_properties, validate_data, render_map"""
    messages = [{"role": "system", "content": plan_prompt}, *history, {"role": "user", "content": message}]
    try:
        content, _, _ = await asyncio.wait_for(_call_llm(messages, model=MODEL_AIR, use_tools=False), timeout=10.0)
        return content
    except (asyncio.TimeoutError, Exception):
        return "SIMPLE"


def _validate_result(tool: str, args: dict, result: dict) -> tuple[bool, str]:
    if not isinstance(result, dict):
        return True, "ok"
    if "error" in result:
        return False, result["error"]
    suspicious = [
        (tool == "dem_analyze" and result.get("statistics", {}).get("min_elevation_m", 9999) < -100, "高程异常低于-100m"),
        (tool == "flood_assessment" and result.get("avg_flood_depth_cm", 0) > 1000, "积水深度超过10m，不合理"),
        (tool == "runoff_compute" and result.get("runoff_volume_m3", 0) < 0, "径流体积为负"),
        (tool == "design_storm" and result.get("peak_intensity_mm_per_hr", 0) > 500, "暴雨强度超过500mm/h，异常"),
    ]
    for cond, msg in suspicious:
        if cond:
            return False, msg
    return True, "ok"


def _trim_context(messages: list[dict]) -> list[dict]:
    total = sum(len(str(m.get("content", ""))) for m in messages)
    if total <= MAX_CONTEXT_CHARS:
        return messages
    system = messages[0] if messages and messages[0].get("role") == "system" else None
    rest = messages[1:] if system else messages
    while rest and sum(len(str(m.get("content", ""))) for m in rest) > MAX_CONTEXT_CHARS - 500:
        removed = False
        for i in range(len(rest) - 1):
            if rest[i].get("role") == "assistant" and rest[i].get("tool_calls"):
                tool_count = 0
                j = i + 1
                while j < len(rest) and rest[j].get("role") == "tool":
                    tool_count += 1
                    j += 1
                if tool_count > 0:
                    rest = rest[:i] + rest[j:]
                    removed = True
                    break
        if not removed:
            for i in range(min(2, len(rest))):
                if rest[i].get("role") not in ("tool",):
                    rest = rest[:i] + rest[i + 1:]
                    removed = True
                    break
            if not removed:
                break
    result = [system, *rest] if system else rest
    cleaned = [result[0]] if result and result[0].get("role") == "system" else []
    source = result[1:] if cleaned else result
    for m in source:
        if m.get("role") == "tool" and (not cleaned or cleaned[-1].get("role") != "assistant" or not cleaned[-1].get("tool_calls")):
            continue
        cleaned.append(m)
    if len(cleaned) < 2 and messages:
        return messages
    return cleaned


def _sweep_cache():
    global _last_cache_sweep
    now = time.time()
    if now - _last_cache_sweep < 60:
        return
    _last_cache_sweep = now
    expired = [k for k, (ts, _) in _tool_cache.items() if now - ts > CACHE_TTL]
    for k in expired:
        del _tool_cache[k]


async def _call_mcp_tool(server: str, tool: str, args: dict, retries: int = 2) -> dict:
    url = MCP_SERVERS.get(server, "")
    if not url:
        return {"error": f"Unknown server: {server}"}
    last_err = ""
    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{url}/call_tool", json={"name": tool, "arguments": args})
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            last_err = str(e)[:200]
            if attempt < retries:
                await asyncio.sleep(0.5 * (attempt + 1))
    return {"error": last_err}


async def _cached_mcp_call(server: str, tool: str, args: dict) -> dict:
    breaker_key = f"{server}.{tool}"
    breaker_entry = _circuit_breaker.get(breaker_key)
    if breaker_entry:
        fail_count, last_fail_ts = breaker_entry
        if fail_count >= BREAKER_THRESHOLD and time.time() - last_fail_ts < BREAKER_COOLDOWN:
            return {"error": f"熔断: {tool}连续失败{BREAKER_THRESHOLD}次，{int(BREAKER_COOLDOWN - (time.time() - last_fail_ts))}秒后重试"}
        if fail_count >= BREAKER_THRESHOLD:
            del _circuit_breaker[breaker_key]

    key = hashlib.md5(f"{server}.{tool}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}".encode()).hexdigest()
    if key in _tool_cache:
        ts, cached = _tool_cache[key]
        if time.time() - ts < CACHE_TTL:
            _tool_cache.move_to_end(key)
            return cached
        del _tool_cache[key]

    result = await _call_mcp_tool(server, tool, args)

    if isinstance(result, dict) and "error" in result:
        prev = _circuit_breaker.get(breaker_key, (0, 0.0))
        _circuit_breaker[breaker_key] = (prev[0] + 1, time.time())
    else:
        _circuit_breaker.pop(breaker_key, None)

    _tool_cache[key] = (time.time(), result)
    while len(_tool_cache) > CACHE_MAX:
        _tool_cache.popitem(last=False)
    _sweep_cache()
    return result


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
    return {"status": "healthy", "service": "web", "engine": "react-fc-v2", "tools": len(GLM_TOOLS)}


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
        return {"error": f"Unsupported format: {ext}"}
    dest = UPLOAD_DIR / file.filename
    content = await file.read()
    dest.write_bytes(content)
    info: dict[str, Any] = {"filename": file.filename, "size_bytes": len(content), "path": str(dest)}
    if ext in (".geojson", ".json"):
        try:
            data = json.loads(content)
            if data.get("type") == "FeatureCollection":
                info["format"] = "GeoJSON"
                info["features"] = len(data.get("features", []))
            elif data.get("type") in ("Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"):
                info["format"] = "GeoJSON"
                info["features"] = 1
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
            except (json.JSONDecodeError, TypeError):
                pass

        ui_force = _detect_ui_action(message)
        if ui_force:
            yield _sse({"type": "thinking_start", "agent": "react", "label": "🧠 自主推理"})
            yield _sse({"type": "thinking", "agent": "react", "content": f"检测到UI意图: {ui_force}"})
            yield _sse({"type": "thinking_end", "agent": "react"})
            yield _sse({"type": "ui_action", "action": ui_force, "args": {"action": ui_force}})
            labels = {"open_3d": "🛰️ 已为您打开三维地形查看器", "open_tin": "🔺 已生成TIN三角网", "open_quadtree": "🌳 已生成四叉树剖分"}
            async for ch in _stream_words(labels.get(ui_force, f"UI: {ui_force}")):
                yield _sse({"type": "text", "content": ch})
            yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": 0})
            return

        yield _sse({"type": "thinking_start", "agent": "planner", "label": "📋 任务规划"})
        plan = await _route(message, parsed_history)
        plan_upper = plan.strip().upper()
        is_simple = plan_upper.startswith("SIMPLE")
        is_direct = plan_upper.startswith("DIRECT:")
        direct_tool = plan.split(":", 1)[1].strip() if is_direct else ""
        if is_simple:
            yield _sse({"type": "thinking", "agent": "planner", "content": "简单查询，直接执行"})
        elif is_direct:
            yield _sse({"type": "thinking", "agent": "planner", "content": f"直接调用: {direct_tool}"})
        else:
            yield _sse({"type": "thinking", "agent": "planner", "content": f"📋 执行计划:\n{plan[:300]}"})
        yield _sse({"type": "thinking_end", "agent": "planner"})

        react_messages: list[dict] = [
            {"role": "system", "content": REACT_SYSTEM_PROMPT},
            *parsed_history,
            {"role": "user", "content": message},
        ]
        if is_direct:
            react_messages.append({"role": "assistant", "content": f"好的，直接调用 {direct_tool} 工具。"})
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

        react_max = 3 if is_direct else MAX_REACT_STEPS
        executed: set[str] = set()
        total_tools = 0

        yield _sse({"type": "thinking_start", "agent": "react", "label": "🧠 自主推理"})

        for step in range(1, react_max + 1):
            yield _sse({"type": "thinking", "agent": "react", "content": f"━━━ 推理步骤 {step}/{react_max} ━━━"})

            try:
                content, reasoning, tool_calls = await _call_llm(react_messages, model=MODEL_FLASH)
            except Exception as e:
                yield _sse({"type": "thinking", "agent": "react", "content": f"❌ LLM失败: {str(e)[:80]}"})
                break

            if reasoning:
                yield _sse({"type": "thinking", "agent": "react", "content": f"💭 {reasoning.replace(chr(10), ' ').strip()[:120]}..."})

            if content and not tool_calls:
                is_multi_step = not is_simple and not is_direct
                if is_multi_step and total_tools < len([l for l in plan.split('\n') if l.strip() and l.strip()[0].isdigit()]):
                    react_messages.append({"role": "user", "content": "计划未完成，请继续调用下一个工具。不要回复文字，只调工具。"})
                    yield _sse({"type": "thinking", "agent": "react", "content": "⏩ 计划未完成，强制继续..."})
                    continue
                yield _sse({"type": "thinking", "agent": "react", "content": f"✅ 推理完成，共{step}步，调用{total_tools}个工具"})
                yield _sse({"type": "thinking_end", "agent": "react"})
                async for ch in _stream_words(content):
                    yield _sse({"type": "text", "content": ch})
                yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools})
                return

            if not tool_calls:
                yield _sse({"type": "thinking_end", "agent": "react"})
                async for ch in _stream_words("抱歉，我暂时无法处理您的请求。请描述具体的水利分析需求。"):
                    yield _sse({"type": "text", "content": ch})
                yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools})
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
                yield _sse({"type": "thinking_end", "agent": "react"})
                async for ch in _stream_words("抱歉，工具调用格式异常。请重新描述您的需求。"):
                    yield _sse({"type": "text", "content": ch})
                yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools})
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
                args_key = hashlib.md5(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                dedup = f"{tool_name}:{args_key}"
                if dedup in executed:
                    yield _sse({"type": "thinking", "agent": "react", "content": f"⏭️ 跳过重复: {tool_name}"})
                    cache_lookup = hashlib.md5(f"{TOOL_TO_SERVER.get(tool_name, '')}.{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}".encode()).hexdigest()
                    cached_entry = _tool_cache.get(cache_lookup)
                    cached_summary = ""
                    if cached_entry:
                        _, cached_val = cached_entry
                        if isinstance(cached_val, dict):
                            cached_summary = _compress_result(tool_name, cached_val)
                    react_messages.append({"role": "tool", "tool_call_id": tc["id"], "content": cached_summary or "该工具已执行过，结果已在上方。请继续执行下一步。"})
                    continue
                executed.add(dedup)
                deduped_calls.append((tc["id"], tool_name, args))

            tasks = [(tc_id, tool_name, TOOL_TO_SERVER.get(tool_name, ""), args) for tc_id, tool_name, args in deduped_calls]
            results = await asyncio.gather(*[_cached_mcp_call(s, n, a) for _, n, s, a in tasks], return_exceptions=True)

            for i, ((tc_id, tool_name, server, args), result) in enumerate(zip(tasks, results)):
                if isinstance(result, Exception):
                    result = {"error": str(result)[:200]}

                total_tools += 1
                label = AGENT_LABELS.get(server, server)

                valid, validation_msg = _validate_result(tool_name, args, result if isinstance(result, dict) else {})
                if not valid:
                    yield _sse({"type": "thinking", "agent": "reflect", "content": f"🔍 反思: {tool_name}结果异常 — {validation_msg}"})
                    yield _sse({"type": "tool_error", "server": server, "tool": tool_name, "error": validation_msg})
                    result = {"error": f"验证失败: {validation_msg}", "original_keys": list(result.keys()) if isinstance(result, dict) else []}

                yield _sse({"type": "divider", "content": f"⚡ Step {step}: {label} → {tool_name}"})
                yield _sse({"type": "tool_start", "server": server, "tool": tool_name, "step": total_tools, "react_step": step})
                yield _sse({"type": "tool_result", "server": server, "tool": tool_name, "result": result, "elapsed_ms": 0})

                summary = _format_tool_summary(server, tool_name, result)
                async for ch in _stream_words(summary):
                    yield _sse({"type": "text", "content": ch})

                compressed = _compress_result(tool_name, result) if isinstance(result, dict) else str(result)[:200]
                if not is_simple and not is_direct and plan:
                    compressed += f"\n\n[已完成{total_tools}个工具。请继续执行计划中的下一步工具调用，不要回复文字。]"
                react_messages.append({"role": "tool", "tool_call_id": tc_id, "content": compressed})

            react_messages = _trim_context(react_messages)
            yield _sse({"type": "thinking", "agent": "react", "content": f"📊 已获取{len(deduped_calls)}个工具结果，继续推理..."})

        yield _sse({"type": "thinking", "agent": "react", "content": f"⚠️ 已达最大推理步数({react_max})，总结回复"})
        yield _sse({"type": "thinking_end", "agent": "react"})
        try:
            final_content, _, _ = await _call_llm(react_messages, model=MODEL_AIR, use_tools=False)
            async for ch in _stream_words(final_content):
                yield _sse({"type": "text", "content": ch})
        except Exception:
            async for ch in _stream_words("分析完成。如需更详细结果，请提出更具体的问题。"):
                yield _sse({"type": "text", "content": ch})

        yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": react_max, "tools_called": total_tools})

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _stream_words(text: str, chunk_size: int = 3):
    for i in range(0, len(text), chunk_size):
        yield text[i:i + chunk_size]
        await asyncio.sleep(0.02)


def _format_tool_summary(server: str, tool: str, result: dict | list) -> str:
    if isinstance(result, list):
        result = result[0] if result else {}
    if not isinstance(result, dict):
        return str(result)[:200]

    if tool == "get_parameter":
        entries = result.get("results", [])
        if not entries:
            return f"📋 {result.get('parameter', tool)}: 未找到匹配数据\n"
        lines = [f"📋 {result.get('parameter', tool)} 查询结果：\n"]
        for e in entries[:8]:
            name = e.get("surface", e.get("city", e.get("land_use", "")))
            cond = e.get("condition", e.get("hydrologic_group", ""))
            if "n_typical" in e:
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
        return f"⭕ 缓冲区: {result.get('geometry', {}).get('type', 'unknown')}\n"
    if tool == "overlay":
        return f"📐 叠加: {result.get('operation', '')} → {result.get('geometry', {}).get('type', 'unknown')}\n"
    if tool == "geometry_properties":
        return f"📏 几何: type={result.get('geometry_type')}, valid={result.get('is_valid')}\n"
    if tool == "validate_data":
        return f"✅ 验证: valid={result.get('is_valid')}, issues={result.get('issues_found')}\n"
    if tool == "render_map":
        return f"🗺️ 渲染完成: ~{len(result.get('image_base64', '')) * 3 // 4 // 1024}KB PNG\n"
    if tool == "design_storm":
        return f"🌧️ 暴雨: {result.get('city','')} P={result.get('return_period_years','')}年 峰值{result.get('peak_intensity_mm_per_hr','')}mm/h\n"
    if tool == "runoff_compute":
        return f"💧 径流: 降雨{result.get('rainfall_mm','')}mm → 径流{result.get('runoff_depth_mm','')}mm\n"
    if tool == "swmm_create_model":
        return f"🏗️ SWMM: {result.get('n_subcatchments','')}子汇水\n"
    if tool == "swmm_simulate":
        return f"🔬 SWMM: 峰值{result.get('peak_flow_cms','')}cms 水深{result.get('max_depth_m','')}m\n"
    if tool == "flood_assessment":
        return f"🌊 内涝: [{result.get('risk_level','').upper()}] 积水{result.get('avg_flood_depth_cm','')}cm\n"
    if tool == "flood_inundation_map":
        return f"🗺️ 淹没: {len(result.get('rings',[]))}级 面积{result.get('total_flood_area_m2','')}m²\n"
    if tool == "drainage_assessment":
        st = "✅达标" if result.get('status') == 'adequate' else f"⚠️不足 缺口{result.get('deficit_cms','')}cms"
        return f"🔧 排水: 满管{result.get('full_flow_capacity_cms','')}cms {st}\n"
    if tool == "flood_warning":
        return f"⚠️ 预警: {result.get('warning_level','').upper()}级 → {', '.join(result.get('recommended_actions',[]))}\n"
    if tool == "flood_risk_zones":
        return f"🎯 风险分区: {len(result.get('zones',[]))}个区域\n"
    if tool == "hydrodynamic_2d_sim":
        return f"🌊 2D模拟: {len(result.get('frames',[]))}帧 峰值水深{result.get('peak_max_depth_m','?')}m\n"
    if tool == "dem_analyze":
        s = result.get('slope', {})
        return f"⛰️ 地形: 坡度{s.get('mean_deg','')}° 坡向{result.get('aspect',{}).get('dominant','')}\n"
    if tool == "watershed_delineate":
        return f"🏞️ 流域: {result.get('watershed_area_km2','')}km²\n"
    if tool == "flow_accumulation":
        return f"🌊 河网: {result.get('n_streams','')}条 总长{result.get('total_stream_length_km','')}km\n"
    if tool == "terrain_profile":
        return f"📈 剖面: 长{result.get('total_distance_m','')}m\n"
    if tool == "point_query":
        return f"📍 点位: 高程{result.get('elevation_m','?')}m 坡度{result.get('slope_deg','?')}°\n"
    if tool == "calibrate_suggest":
        return f"🔧 率定: NSE={result.get('nash_sutcliffe','')} → {len(result.get('suggestions',[]))}条建议\n"
    if "error" in result:
        return f"❌ 错误: {result['error']}\n"
    return f"⚙️ {server}.{tool}: {json.dumps(result, ensure_ascii=False)[:200]}\n"


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
