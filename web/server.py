from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import structlog
import uvicorn
from scipy.spatial import Voronoi as _ScipyVoronoi
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv(Path(__file__).parent.parent / ".env")

logger = structlog.get_logger(__name__)

ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")
GLM_API_URL = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"

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
    "raster": "Raster 地形分析", "internal": "Internal 内置服务", "generated": "AutoGen 自动生成",
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
    "raster": ["dem_analyze", "watershed_delineate", "flow_accumulation", "terrain_profile", "point_query", "dem_render", "tin_generate", "quadtree_subdivide", "scatter_interpolate"],
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
- 用户问天气/降雨预报(单点预报) → 调 weather_forecast
- 用户问降水分布/降雨网格/面雨量/暴雨分析(区域网格) → 调 precipitation_grid
- 用户问卫星/遥感影像 → 调 satellite_search

【3D重建规则】
- 用户上传图片后要求"3D重建/三维建模/立体模型/reconstruct"时 → 调 reconstruct_3d
- image_path 从对话上下文中的[上传图片路径:xxx]获取
- 没有[上传图片路径:xxx]时，提示用户先上传图片

【关键规则 - auto_tool 兜底】
以下场景必须调 auto_tool，绝对不能输出Python代码文本：
- 计算/公式/求解/拟合/统计/矩阵/表格/曲线/图表
- 生成/绘制/画 GeoJSON/多边形/线/图形
- 水力计算(渠道/水深/流量/流速/曼宁/梯形/矩形)
- 水文计算(单位线/演进/马斯京根/频率分析)
- 任何需要写代码才能完成的任务
- 找不到合适工具时 → auto_tool 是最终兜底

绝对禁止：输出Python/代码块/代码示例。只能调工具。

可以不调工具的场景：
- 纯寒暄（你好/谢谢/再见）

推理规则：
- 复合任务需多步推理：先获取参数→再计算→最后评估
- 参数从对话上下文提取实际值，不要编造
- 工具返回错误时分析原因并调整参数重试
- 回复专业、准确、有条理
- 关键：完成空间计算后（插值/模拟/地形分析/流域提取等），如果用户要求展示/渲染/出图，必须再调 render_map 将结果渲染到地图上
- 关键：auto_tool生成工具执行成功后，如果结果包含空间数据，必须主动在回复中说明结果并引导用户查看"""


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _detect_ui_action(msg: str) -> str:
    if any(k in msg for k in ["三角网", "TIN", "不规则三角"]):
        return "open_tin"
    if any(k in msg for k in ["四叉树", "Quadtree", "嵌套剖分", "自适应剖分"]):
        return "open_quadtree"
    if any(k in msg for k in ["三维", "3D", "立体", "heightmap", "立体场景", "三维场景", "立体地形", "三维地形"]):
        # 如果用户意图是3D重建，不走UI意图，交给reconstruct_3d工具
        if not any(k in msg for k in ["重建", "reconstruct", "建模", "生成模型", "建模型", "3D模型", "三维模型", "立体模型"]):
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
    if tool == "building_extract":
        return f"建筑提取: {result.get('count','?')}栋 平均高{result.get('avg_height_m','?')}m 总面积{result.get('total_area_m2','?')}m²"
    if tool == "water_monitor":
        return f"水体监测: {result.get('water_body_count','?')}处水体 水面{result.get('total_water_area_km2','?')}km² 覆盖率{result.get('water_coverage_pct','?')}% 日期{result.get('date','?')}"
    if tool == "flood_sim_3d":
        s = result.get("stats", {})
        return f"洪水推演: 降雨{result.get('rainfall_mm','?')}mm 安全{s.get('safe','?')}栋/部分{s.get('partial','?')}栋/淹没{s.get('submerged','?')}栋"
    if tool == "drone_mission":
        return f"无人机航线: {result.get('n_waypoints','?')}航点 {result.get('total_distance_km','?')}km {result.get('estimated_flight_min','?')}min"
    if tool == "water_change":
        return f"水体变化: {result.get('area1_km2','?')}→{result.get('area2_km2','?')}km² ({result.get('change_pct','?'):+.1f}%) {result.get('date1','?')}~{result.get('date2','?')}"
    return json.dumps(result, ensure_ascii=False)[:200]


async def _call_llm(messages: list[dict], model: str = MODEL_FLASH, use_tools: bool = True) -> tuple[str, str, list[dict]]:
    headers = {"Authorization": f"Bearer {ZHIPUAI_API_KEY}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 4096,
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
    (r"水动力|淹没模拟|洪水模拟|二维模拟", "hydrodynamic_2d_sim"),
    (r"什么是|解释|介绍.*概念|原理是|怎么理解", "explain_concept"),
    (r"糙率|曲线数|CN值|管材|水泵|海绵|暴雨参数", "get_parameter"),
    (r"河网提取|水流累积", "flow_accumulation"),
    (r"流域提取|汇水区|子流域划分", "watershed_delineate"),
    (r"高程查询|点位查询|查点高程", "point_query"),
    (r"地形剖面|纵断面|横断面", "terrain_profile"),
    (r"地形分析|DEM分析|DEM坡度", "dem_analyze"),
    (r"TIN三角网|不规则三角|三角剖分", "tin_generate"),
    (r"四叉树|自适应网格|嵌套剖分", "quadtree_subdivide"),
    (r"暴雨雨型|设计暴雨|暴雨强度公式", "design_storm"),
    (r"SCS.CN|径流系数|产汇流", "runoff_compute"),
    (r"淹没范围|淹没地图|淹没面积|淹没图|会不会被水淹|积水", "flood_inundation_map"),
    (r"洪水风险|内涝评估", "flood_assessment"),
    (r"排水能力|排水评估", "drainage_assessment"),
    (r"洪水预警|防汛预警", "flood_warning"),
    (r"风险分区|风险等级", "flood_risk_zones"),
    (r"SWMM|swmm|排水管网", "swmm_simulate"),
    (r"空间关系|相交|包含|相邻|空间查询", "spatial_query"),
    (r"缓冲区|缓冲分析|周边范围", "buffer"),
    (r"叠加分析|交集|并集|差集", "overlay"),
    (r"坐标转换|坐标系转换|EPSG", "coordinate_transform"),
    (r"搜索.*资料|知识库查询", "search"),
    (r"标准检索|查规范|GB\d|SL\d|设计规范", "get_standard"),
    (r"率定|校准|参数优化", "calibrate_suggest"),
    (r"DEM渲染|地形渲染", "dem_render"),
    (r"克里金|Kriging|IDW|反距离权重|RBF插值", "scatter_interpolate"),
    (r"天气预报|降雨预报|气象预报", "weather_forecast"),
    (r"卫星影像|遥感|Sentinel|Landsat", "satellite_search"),
    (r"渲染地图|出图|绘制地图", "render_map"),
]

_COMPUTE_FAST = re.compile(
    r'计算|算[出法]|求解|拟合|统计[分分析]|'
    r'生成.*[GeoJSON多边线图]|绘制.*[图线曲线]|画.*[图线]|'
    r'矩阵|表格|曲线图|柱状图|对比曲线|过程图|'
    r'单位线|演进|调洪|水力计算|水头损失|'
    r'标准差|变异系数|偏态|峰态|频率分析|'
    r'渔网|六边形|网格划分|风暴路径|随机游走|'
    r'曼宁公式|海森威廉|试算法|'
    r'流量.*水深|水深.*流量|流速.*流量',
    re.IGNORECASE
)

_route_cache: dict[str, str] = {}
_ROUTE_CACHE_MAX = 200


_ALL_TOOLS = "hydrodynamic_2d_sim,get_parameter,explain_concept,search,get_standard,dem_analyze,watershed_delineate,flow_accumulation,terrain_profile,point_query,dem_render,tin_generate,quadtree_subdivide,design_storm,runoff_compute,swmm_create_model,swmm_simulate,calibrate_suggest,flood_inundation_map,flood_assessment,drainage_assessment,flood_warning,flood_risk_zones,spatial_query,buffer,overlay,coordinate_transform,geometry_properties,validate_data,render_map,weather_forecast,satellite_search,spatial_knowledge_query,scatter_interpolate,auto_tool,reconstruct_3d,precipitation_grid,building_extract,water_monitor,flood_sim_3d,drone_mission,water_change".split(",")

_ROUTE_SYSTEM = """你是路由模块。只回复工具名或SIMPLE。

【最高优先级】以下类型必须路由到 auto_tool：
- 计算/算/公式/求解/拟合/统计/矩阵/表格/曲线/图表/单位线/演进/水力/渠道/水深/流量/流速
- 生成/绘制/画/创建(GeoJSON/多边形/线/图形/螺旋/网格/缓冲区环/河道)
- 任何数学运算、数值计算、公式推导
- 任何需要写代码才能完成的任务

【次优先级】精确匹配时才用：
- 淹没/积水→flood_inundation_map
- 暴雨强度公式→design_storm
- SWMM/管网→swmm_simulate
- 克里金/IDW→scatter_interpolate
- 缓冲区分析→buffer
- DEM/地形/坡度→dem_analyze
- 渲染地图→render_map

不确定时→auto_tool
只回一个工具名。可选:""" + ",".join(_ALL_TOOLS)


async def _route(message: str, history: list[dict]) -> str:
    if any(kw in message.lower() for kw in SIMPLE_KEYWORDS):
        return "SIMPLE"

    if _COMPUTE_FAST.search(message):
        return "DIRECT:auto_tool"

    for pattern, tool in ROUTING_RULES:
        if re.search(pattern, message):
            return f"DIRECT:{tool}"

    cache_key = hashlib.md5(message.encode()).hexdigest()
    _route_cache.pop(cache_key, None)

    messages = [{"role": "system", "content": _ROUTE_SYSTEM}, {"role": "user", "content": message}]
    try:
        content, _, _ = await asyncio.wait_for(_call_llm(messages, model=MODEL_AIR, use_tools=False), timeout=8.0)
        content = content.strip()
        if content.startswith("DIRECT:"):
            result = content
        elif content.upper() == "SIMPLE":
            result = "SIMPLE"
        else:
            hit = None
            for t in _ALL_TOOLS:
                if t in content:
                    hit = t
                    break
            result = f"DIRECT:{hit}" if hit else "DIRECT:auto_tool"
    except Exception:
        result = "DIRECT:auto_tool"

    if len(_route_cache) >= _ROUTE_CACHE_MAX:
        _route_cache.pop(next(iter(_route_cache)))
    _route_cache[cache_key] = result
    return result





# ═══════════════════════════════════════════════════════════════════════
# 2026 SOTA MODULES: Memory, Debate, Tracing, Commonsense, Multimodal,
#   ToT, Weather, DigitalTwin, SelfEvolving, ToolGen, NeuroSymbolic,
#   Satellite, KnowledgeGraph, WorldModel
# ═══════════════════════════════════════════════════════════════════════

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── 1. Agent Memory System (SQLite) ──────────────────────────────────

class MemoryStore:
    def __init__(self):
        self.db_path = DATA_DIR / "agent_memory.db"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, user_msg TEXT, tool_calls TEXT,
                    result_summary TEXT, ts REAL
                );
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE, value TEXT, source TEXT, ts REAL
                );
                CREATE TABLE IF NOT EXISTS procedures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger_pattern TEXT, tool_sequence TEXT,
                    success_count INTEGER DEFAULT 1, ts REAL
                );
                CREATE INDEX IF NOT EXISTS idx_ep_msg ON episodes(user_msg);
                CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);
            """)

    def save_episode(self, session_id: str, user_msg: str, tool_calls: list, summary: str):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("INSERT INTO episodes(session_id,user_msg,tool_calls,result_summary,ts) VALUES(?,?,?,?,?)",
                         (session_id, user_msg[:500], json.dumps(tool_calls, ensure_ascii=False)[:2000], summary[:500], time.time()))

    def recall_episodes(self, query: str, limit: int = 3) -> list[dict]:
        words = re.findall(r"[\u4e00-\u9fff\w]{2,}", query)[:5]
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT user_msg,tool_calls,result_summary,ts FROM episodes ORDER BY ts DESC LIMIT 50").fetchall()
        scored = []
        for r in rows:
            score = sum(1 for w in words if w in r[0] or w in r[2])
            if score > 0:
                scored.append({"user_msg": r[0], "tools": r[1][:200], "summary": r[2], "ts": r[3], "score": score})
        scored.sort(key=lambda x: -x["score"])
        return scored[:limit]

    def save_fact(self, key: str, value: str, source: str = "agent"):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("INSERT OR REPLACE INTO facts(key,value,source,ts) VALUES(?,?,?,?)",
                         (key, value[:500], source, time.time()))

    def recall_facts(self, prefix: str = "", limit: int = 10) -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            if prefix:
                rows = conn.execute("SELECT key,value,source FROM facts WHERE key LIKE ? ORDER BY ts DESC LIMIT ?",
                                    (f"{prefix}%", limit)).fetchall()
            else:
                rows = conn.execute("SELECT key,value,source FROM facts ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [{"key": r[0], "value": r[1], "source": r[2]} for r in rows]

    def save_procedure(self, trigger: str, tool_seq: list):
        seq_str = json.dumps(tool_seq, ensure_ascii=False)
        with sqlite3.connect(str(self.db_path)) as conn:
            existing = conn.execute("SELECT id,success_count FROM procedures WHERE trigger_pattern=?", (trigger,)).fetchone()
            if existing:
                conn.execute("UPDATE procedures SET success_count=success_count+1,ts=? WHERE id=?", (time.time(), existing[0]))
            else:
                conn.execute("INSERT INTO procedures(trigger_pattern,tool_sequence,ts) VALUES(?,?,?)", (trigger, seq_str, time.time()))

    def recall_procedures(self, query: str, limit: int = 3) -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT trigger_pattern,tool_sequence,success_count FROM procedures ORDER BY success_count DESC LIMIT 20").fetchall()
        scored = []
        for r in rows:
            pattern_words = re.findall(r"[\u4e00-\u9fff\w]{2,}", r[0])
            score = sum(1 for w in pattern_words if w in query)
            if score > 0:
                scored.append({"trigger": r[0], "tools": r[1], "success": r[2], "score": score})
        scored.sort(key=lambda x: -x["score"])
        return scored[:limit]


_memory = MemoryStore()


# ── 2. Multi-Agent Debate Validation ─────────────────────────────────

CRITICAL_TOOLS = {"hydrodynamic_2d_sim", "flood_assessment", "flood_risk_zones", "swmm_simulate", "flood_inundation_map"}
DEBATE_PROMPTS = {
    "physics": "你是水力学物理验证专家。验证以下工具结果是否符合水力学物理规律。返回JSON: {\"pass\":bool,\"score\":1-10,\"issue\":\"\"}",
    "data": "你是数据合理性验证专家。验证以下工具结果的数值范围是否合理。返回JSON: {\"pass\":bool,\"score\":1-10,\"issue\":\"\"}",
    "completeness": "你是任务完整性验证专家。验证以下工具结果是否完整回答了用户需求。返回JSON: {\"pass\":bool,\"score\":1-10,\"issue\":\"\"}",
}


async def _debate_validate(query: str, tool_name: str, tool_result: dict) -> dict:
    if tool_name not in CRITICAL_TOOLS:
        return {"consensus": True, "critics": []}
    result_str = json.dumps(tool_result, ensure_ascii=False, default=str)[:1500]
    async def _critic(role: str, prompt: str) -> dict:
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"用户问题: {query}\n工具: {tool_name}\n结果: {result_str}"}
        ]
        try:
            content, _, _ = await asyncio.wait_for(_call_llm(messages, model=MODEL_FLASH, use_tools=False), timeout=10.0)
            match = re.search(r'\{[^}]+\}', content)
            if match:
                return json.loads(match.group()) | {"role": role}
        except Exception:
            pass
        return {"role": role, "pass": True, "score": 5, "issue": "timeout"}

    critics = await asyncio.gather(*[_critic(r, p) for r, p in DEBATE_PROMPTS.items()])
    passes = sum(1 for c in critics if c.get("pass"))
    avg_score = sum(c.get("score", 5) for c in critics) / max(len(critics), 1)
    consensus = passes >= 2 and avg_score >= 6
    return {"consensus": consensus, "critics": list(critics)}


# ── 3. Observability Tracing ─────────────────────────────────────────

@dataclass
class TraceSpan:
    trace_id: str
    query: str
    t_start: float
    events: list = field(default_factory=list)

    def add(self, name: str, detail: str = "", duration_ms: float = 0):
        self.events.append({"name": name, "ts": time.time(), "detail": detail, "duration_ms": int(duration_ms)})

    def to_dict(self) -> dict:
        return {"trace_id": self.trace_id, "query": self.query, "duration_ms": int((time.time() - self.t_start) * 1000), "events": self.events}


_traces: OrderedDict[str, TraceSpan] = OrderedDict()
_trace_counter = 0


def _new_trace(query: str) -> TraceSpan:
    global _trace_counter
    _trace_counter += 1
    span = TraceSpan(trace_id=f"tr_{_trace_counter:06d}", query=query, t_start=time.time())
    _traces[span.trace_id] = span
    while len(_traces) > 100:
        _traces.popitem(last=False)
    return span


# ── 4. Spatial Commonsense Knowledge ─────────────────────────────────

SPATIAL_COMMONSENSE = {
    "hydrology": [
        "水往低处流 — 水流方向由高程决定",
        "汇流累积量越大河道越宽",
        "糙率越大流速越慢水深越深",
        "暴雨强度随重现期增大而增大",
        "SCS-CN值越高产流量越大",
        "径流系数=径流量/降雨量 范围0-1",
    ],
    "flood": [
        "淹没区域沿河道和低洼地带分布",
        "洪水峰值出现在降雨峰值后一段时间",
        "淹没深度随距河道距离增加而减小",
        "百年一遇>五十年一遇>二十年一遇",
        "城市内涝点通常位于低洼区域",
    ],
    "terrain": [
        "坡度=高程差/水平距离",
        "坡向决定日照和融雪方向",
        "流域面积越大汇流时间越长",
        "DEM分辨率越高地形细节越丰富",
    ],
}

PHYSICS_RANGES = {
    "manning_n": (0.01, 0.30, "糙率"),
    "cn_value": (0, 100, "CN曲线数"),
    "slope_deg": (0, 90, "坡度"),
    "velocity_ms": (0, 15, "流速(m/s)"),
    "water_depth_m": (0, 50, "水深(m)"),
    "flood_depth_m": (0, 30, "洪水深度(m)"),
    "elevation_m": (790, 1800, "研究区高程(m)"),
    "rainfall_mmh": (0, 300, "降雨强度(mm/h)"),
    "runoff_coeff": (0, 1, "径流系数"),
}


def _inject_commonsense(query: str) -> str:
    rules = []
    q = query.lower()
    if any(k in q for k in ["淹没", "洪水", "积水", "内涝", "涝"]):
        rules.extend(SPATIAL_COMMONSENSE["flood"])
    if any(k in q for k in ["径流", "降雨", "暴雨", "汇流", "产流"]):
        rules.extend(SPATIAL_COMMONSENSE["hydrology"])
    if any(k in q for k in ["坡度", "高程", "地形", "dem", "流域", "河网"]):
        rules.extend(SPATIAL_COMMONSENSE["terrain"])
    if not rules:
        rules = SPATIAL_COMMONSENSE["hydrology"][:3]
    return "[空间常识] " + "; ".join(rules[:5])


def _validate_physics(tool_name: str, result: dict) -> list[str]:
    warnings = []
    if not isinstance(result, dict):
        return warnings
    if tool_name == "hydrodynamic_2d_sim":
        depth = result.get("peak_max_depth_m", 0)
        if isinstance(depth, (int, float)) and depth > 30:
            warnings.append(f"峰值水深{depth}m超出合理范围(0-30m)")
    if tool_name == "runoff_compute":
        coeff = result.get("runoff_coefficient", 0)
        if isinstance(coeff, (int, float)) and (coeff < 0 or coeff > 1):
            warnings.append(f"径流系数{coeff}超出合理范围(0-1)")
    if tool_name == "flood_assessment":
        depth_cm = result.get("avg_flood_depth_cm", 0)
        if isinstance(depth_cm, (int, float)) and depth_cm > 1000:
            warnings.append(f"积水深度{depth_cm}cm异常(>1000cm)")
    return warnings


# ── 5. Multimodal (GLM-4V) ───────────────────────────────────────────

MODEL_VISION = "glm-4v-flash"
UPLOAD_IMG_DIR = DATA_DIR / "uploads_img"
UPLOAD_IMG_DIR.mkdir(parents=True, exist_ok=True)


async def _analyze_image(image_b64: str, prompt: str = "") -> str:
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt or "分析这张与水利/地理相关的图片，识别关键信息（地形、水域、建筑、植被等），给出结构化描述。"},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64[:50000]}"}}
    ]}]
    headers = {"Authorization": f"Bearer {ZHIPUAI_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": MODEL_VISION, "messages": messages}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(GLM_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"].get("content", "")


# ── 6. Tree-of-Thought Reasoning ─────────────────────────────────────

async def _tree_of_thought(query: str, breadth: int = 3) -> str:
    branches = []
    for i in range(breadth):
        messages = [
            {"role": "system", "content": f"你是水利空间智能规划师。为用户需求制定执行方案(方案变体#{i+1})。回复格式: 1. 步骤 [工具名]\n2. ..."},
            {"role": "user", "content": query}
        ]
        try:
            plan, _, _ = await asyncio.wait_for(_call_llm(messages, model=MODEL_AIR, use_tools=False), timeout=12.0)
            eval_msg = [{"role": "system", "content": "评估此方案的可行性，返回JSON: {\"score\":1-10}"},
                        {"role": "user", "content": plan}]
            eval_c, _, _ = await asyncio.wait_for(_call_llm(eval_msg, model=MODEL_FLASH, use_tools=False), timeout=8.0)
            match = re.search(r'"score"\s*:\s*(\d+)', eval_c)
            score = int(match.group(1)) if match else 5
            branches.append({"plan": plan, "score": min(score, 10)})
        except Exception:
            branches.append({"plan": "", "score": 0})
    branches.sort(key=lambda x: -x["score"])
    best = branches[0]
    return best["plan"] if best["score"] >= 4 else ""


# ── 7. Weather Forecast (Open-Meteo, free) ───────────────────────────

_weather_cache: dict[str, tuple[float, Any]] = {}


async def _get_weather(lat: float = 33.19, lon: float = 104.89, days: int = 3) -> dict:
    cache_key = f"{lat:.2f}_{lon:.2f}"
    if cache_key in _weather_cache and time.time() - _weather_cache[cache_key][0] < 1800:
        return _weather_cache[cache_key][1]
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=precipitation,temperature_2m,wind_speed_10m&forecast_days={days}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            _weather_cache[cache_key] = (time.time(), data)
            return data
    except Exception as e:
        return {"error": str(e)[:200]}


_precip_cache: dict[str, tuple[float, dict]] = {}
_last_flood_result: dict | None = None
_last_flood_time: float = 0
_last_flood_bbox: list[float] | None = None


async def _fetch_precipitation_grid(
    bbox: list[float] | None = None,
    date_start: str = "",
    date_end: str = "",
    grid_size: int = 8,
    forecast_mode: bool = False,
    location: str = "",
) -> dict:
    from datetime import datetime, timedelta

    if not bbox or len(bbox) < 4:
        if location:
            coord = await _geocode_city(location)
            if coord:
                cx, cy = coord
                half = 0.4
                bbox = [cx - half, cy - half, cx + half, cy + half]
        if not bbox:
            bbox = [104.5, 33.0, 105.3, 33.5]
    west, south, east, north = bbox[0], bbox[1], bbox[2], bbox[3]

    min_span = 0.5
    cx, cy = (west + east) / 2, (south + north) / 2
    if abs(east - west) < min_span or abs(north - south) < min_span:
        west = cx - min_span / 2
        east = cx + min_span / 2
        south = cy - min_span / 2
        north = cy + min_span / 2

    gs = max(4, min(grid_size, 12))

    today = datetime.now().strftime("%Y-%m-%d")
    if forecast_mode:
        date_start = today
        date_end = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    else:
        if not date_end:
            date_end = today
        if not date_start:
            date_start = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    cache_key = f"{west:.2f}_{south:.2f}_{east:.2f}_{north:.2f}_{date_start}_{date_end}_{gs}"
    if cache_key in _precip_cache and time.time() - _precip_cache[cache_key][0] < 600:
        return _precip_cache[cache_key][1]

    lats: list[float] = []
    lons: list[float] = []
    for i in range(gs):
        lat = south + (north - south) * i / (gs - 1)
        for j in range(gs):
            lon = west + (east - west) * j / (gs - 1)
            lats.append(round(lat, 4))
            lons.append(round(lon, 4))

    seen: dict[str, int] = {}
    uniq_lats: list[float] = []
    uniq_lons: list[float] = []
    remap: list[int] = []
    for i in range(len(lats)):
        key = f"{lats[i]:.4f},{lons[i]:.4f}"
        if key not in seen:
            seen[key] = len(uniq_lats)
            uniq_lats.append(lats[i])
            uniq_lons.append(lons[i])
        remap.append(seen[key])

    lat_str = ",".join(str(x) for x in uniq_lats)
    lon_str = ",".join(str(x) for x in uniq_lons)

    is_forecast = date_end >= today and date_start >= today
    if is_forecast:
        base_url = "https://api.open-meteo.com/v1/forecast"
        model_param = ""
    else:
        base_url = "https://archive-api.open-meteo.com/v1/archive"
        model_param = "&models=era5_land"
    url = (
        f"{base_url}?latitude={lat_str}&longitude={lon_str}"
        f"&hourly=precipitation&start_date={date_start}&end_date={date_end}&timezone=Asia/Shanghai{model_param}"
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.json()
    except Exception as e:
        return {"error": f"Open-Meteo API请求失败: {str(e)[:150]}"}

    if isinstance(raw, list):
        data_list = raw
    else:
        data_list = [raw]

    time_labels: list[str] = []
    uniq_vals: list[list[float]] = []
    for idx, pt in enumerate(data_list):
        hourly = pt.get("hourly", {})
        times = hourly.get("time", [])
        vals = hourly.get("precipitation", [])
        if not time_labels:
            time_labels = times
        uniq_vals.append([float(v) if v is not None else 0.0 for v in vals])

    precip_matrix: list[list[float]] = []
    for t_idx in range(len(time_labels)):
        frame = []
        for grid_idx in range(len(lats)):
            uidx = remap[grid_idx]
            frame.append(uniq_vals[uidx][t_idx] if t_idx < len(uniq_vals[uidx]) else 0.0)
        precip_matrix.append(frame)

    if not time_labels or not precip_matrix:
        return {"error": "未获取到降水数据"}

    grid_lats = []
    grid_lons = []
    for i in range(gs):
        for j in range(gs):
            grid_lats.append(lats[i * gs + j])
            grid_lons.append(lons[i * gs + j])

    area_avg: list[float] = []
    all_vals: list[float] = []
    for frame in precip_matrix:
        avg = sum(frame) / len(frame) if frame else 0
        area_avg.append(round(avg, 2))
        all_vals.extend(frame)

    max_val = max(all_vals) if all_vals else 0
    mean_val = sum(all_vals) / len(all_vals) if all_vals else 0
    total_val = sum(area_avg)

    peak_idx = area_avg.index(max(area_avg)) if area_avg else 0
    peak_time = time_labels[peak_idx] if peak_idx < len(time_labels) else ""

    storm_centers: list[dict] = []
    for t_idx, frame in enumerate(precip_matrix):
        if not frame or max(frame) <= 0:
            continue
        max_val_t = max(frame)
        g_idx = frame.index(max_val_t)
        sc_lat = grid_lats[g_idx] if g_idx < len(grid_lats) else 0
        sc_lon = grid_lons[g_idx] if g_idx < len(grid_lons) else 0
        storm_centers.append({
            "time": time_labels[t_idx],
            "lat": round(sc_lat, 4),
            "lon": round(sc_lon, 4),
            "mm": round(max_val_t, 2),
            "place": "",
        })

    if storm_centers:
        peak_sc = max(storm_centers, key=lambda s: s["mm"])
        try:
            async with httpx.AsyncClient(timeout=10) as gc:
                resp = await gc.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={"lat": peak_sc["lat"], "lon": peak_sc["lon"], "format": "json", "zoom": 14, "accept-language": "zh"},
                    headers={"User-Agent": "S-AI/1.0"},
                )
                addr = resp.json().get("address", {})
                parts = [addr.get("village"), addr.get("town"), addr.get("county")]
                place = "·".join([p for p in parts if p]) or addr.get("county", "")
                peak_sc["place"] = place
        except Exception:
            pass

    peak_grid_idx = precip_matrix[peak_idx].index(max(precip_matrix[peak_idx])) if precip_matrix[peak_idx] else 0
    peak_lat = grid_lats[peak_grid_idx] if peak_grid_idx < len(grid_lats) else 0
    peak_lon = grid_lons[peak_grid_idx] if peak_grid_idx < len(grid_lons) else 0

    result = {
        "precipitation_grid": True,
        "bbox": [west, south, east, north],
        "date_start": date_start,
        "date_end": date_end,
        "grid_size": gs,
        "data_source": "ERA5-Land 0.1° (~9km)" if not is_forecast else "Open-Meteo Forecast (~11km)",
        "resolution_km": 9 if not is_forecast else 11,
        "time_steps": time_labels,
        "grid_lats": grid_lats,
        "grid_lons": grid_lons,
        "precipitation_matrix": precip_matrix,
        "area_average_series": [{"time": t, "value_mm": v} for t, v in zip(time_labels, area_avg)],
        "storm_centers": storm_centers,
        "stats": {
            "max_mm": round(max_val, 2),
            "mean_mm": round(mean_val, 2),
            "total_area_avg_mm": round(total_val, 2),
            "peak_time": peak_time,
            "peak_intensity_mm_hr": round(max(area_avg) if area_avg else 0, 2),
            "peak_center": {"lat": round(peak_lat, 4), "lon": round(peak_lon, 4)},
        },
    }

    _precip_cache[cache_key] = (time.time(), result)
    return result


_CITY_COORDS = {
    "天水": (105.7249, 34.5809), "兰州": (103.8343, 36.0611), "西安": (108.9398, 34.3416),
    "北京": (116.4074, 39.9042), "上海": (121.4737, 31.2304), "成都": (104.0657, 30.5723),
    "重庆": (106.5516, 29.5630), "武汉": (114.3055, 30.5928), "南京": (118.7969, 32.0603),
    "杭州": (120.1551, 30.2741), "广州": (113.2644, 23.1291), "深圳": (114.0579, 22.5431),
    "陇南": (104.9219, 33.3886), "定西": (104.6264, 35.5796), "平凉": (106.6652, 35.5428),
    "白龙江": (104.9219, 33.3886), "嘉陵江": (106.1080, 32.5400), "渭河": (108.9398, 34.3416),
    "黄河": (106.2309, 38.4872), "洮河": (103.8343, 35.3000), "大夏河": (102.5000, 35.5000),
    "西汉水": (105.7000, 33.8000), "通天河": (104.3000, 33.0000),
    "庆阳": (107.6380, 35.7342), "酒泉": (98.4941, 39.7320), "张掖": (100.4496, 38.9252),
    "武威": (102.6385, 37.9283), "白银": (104.1386, 36.5447), "嘉峪关": (98.2773, 39.7865),
    "金昌": (102.1880, 38.5160), "临夏": (103.2104, 35.6011), "甘南": (102.9109, 34.9834),
    "赤峰": (118.8889, 42.2576), "呼和浩特": (111.7519, 40.8414), "沈阳": (123.4290, 41.7969),
    "哈尔滨": (126.5358, 45.8023), "长春": (125.3245, 43.8868), "天津": (117.1901, 39.1252),
    "郑州": (113.6253, 34.7466), "长沙": (112.9388, 28.2282), "南昌": (115.8581, 28.6829),
    "合肥": (117.2272, 31.8206), "福州": (119.2964, 26.0745), "昆明": (102.8329, 24.8801),
    "贵阳": (106.7135, 26.5783), "拉萨": (91.1409, 29.6457), "银川": (106.2309, 38.4872),
    "西宁": (101.7782, 36.6171), "乌鲁木齐": (87.6168, 43.8256), "太原": (112.5489, 37.8706),
    "石家庄": (114.5149, 38.0428), "济南": (117.1205, 36.6510), "海口": (110.3312, 20.0317),
    "南宁": (108.3669, 22.8170), "包头": (109.8403, 40.6574),
}


async def _geocode_city(name: str) -> tuple[float, float] | None:
    for city, coord in _CITY_COORDS.items():
        if city in name:
            return coord
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": name, "format": "json", "limit": 1, "accept-language": "zh"},
                headers={"User-Agent": "S-AI/1.0"},
            )
            data = resp.json()
            if data:
                return float(data[0]["lon"]), float(data[0]["lat"])
    except Exception:
        pass
    return None


async def _extract_buildings(bbox=None, location=None):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from segment.osm_buildings import fetch_osm_buildings

    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        if location:
            coord = await _geocode_city(location)
            if coord:
                cx, cy = coord
                half = 0.0075
                bbox = [cx - half, cy - half, cx + half, cy + half]
                logger.info(f"[building_extract] Geocoded '{location}' -> ({cx:.4f}, {cy:.4f})")
        if not bbox:
            bbox = [105.725, 34.580, 105.745, 34.595]
    west, south, east, north = bbox

    max_span = 0.02
    cx, cy = (west + east) / 2, (south + north) / 2
    if abs(east - west) > max_span or abs(north - south) > max_span:
        west = cx - max_span / 2
        east = cx + max_span / 2
        south = cy - max_span / 2
        north = cy + max_span / 2
    bbox = [west, south, east, north]

    logger.info(f"[building_extract] Querying OSM buildings bbox={bbox}")
    try:
        features = await fetch_osm_buildings(bbox)
    except Exception as e:
        logger.warning(f"[building_extract] OSM failed: {e}, falling back to SAM")
        features = []

    if len(features) < 3:
        logger.info(f"[building_extract] OSM only {len(features)} buildings, falling back to SAM")
        from segment.tile_fetcher import fetch_tiles_for_bbox
        from segment.engine import segment_buildings
        zoom = 18
        tile_data = await fetch_tiles_for_bbox(west, south, east, north, zoom=zoom)
        result = await asyncio.to_thread(segment_buildings, tile_data["image"], tile_data["bbox"])
        result["data_source"] = "ArcGIS World Imagery + SAM vit_b (fallback)"
        result["zoom"] = tile_data["zoom"]
        result["n_tiles"] = tile_data["n_tiles"]
    else:
        avg_h = sum(f["properties"]["height_m"] for f in features) / len(features)
        total_a = sum(f["properties"]["area_m2"] for f in features)
        result = {
            "buildings": features,
            "count": len(features),
            "avg_height_m": round(avg_h, 1),
            "total_area_m2": round(total_a, 1),
            "bbox": bbox,
            "image_size": [0, 0],
            "data_source": "OpenStreetMap (精确轮廓)",
            "zoom": 18,
            "n_tiles": 0,
        }

    result["building_extract"] = True
    logger.info(f"[building_extract] Done: {result['count']} buildings from {result.get('data_source','?')}")
    return result


async def _monitor_water(bbox=None, location=None):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from water_monitor.engine import search_scenes, extract_water

    if location:
        coord = await _geocode_city(location)
        if coord:
            cx, cy = coord
            half = 0.05
            bbox = [cx - half, cy - half, cx + half, cy + half]
            logger.info(f"[water_monitor] Geocoded '{location}' -> ({cx:.4f}, {cy:.4f})")
    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        bbox = [104.85, 33.15, 105.05, 33.35]

    logger.info(f"[water_monitor] Searching Sentinel-2 scenes for bbox={bbox}")
    scenes = await search_scenes(bbox, max_cloud=20, limit=30)
    if not scenes:
        return {"error": "未找到覆盖该区域的低云量Sentinel-2影像，请尝试其他日期范围或区域"}

    logger.info(f"[water_monitor] Found {len(scenes)} scenes, best: {scenes[0]['date']} cloud={scenes[0]['cloud']:.1f}%")
    result = await asyncio.to_thread(extract_water, bbox, scenes[0])
    result["water_monitor"] = True
    result["data_source"] = "Sentinel-2 L2A (10m)"
    result["satellite"] = scenes[0]["scene_id"]
    result["available_dates"] = [s["date"] for s in scenes[:5]]

    logger.info(f"[water_monitor] Done: {result['water_body_count']} water bodies, {result['total_water_area_km2']}km2")
    return result


async def _detect_water_change(bbox=None, location=None, date1="", date2=""):
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from water_monitor.engine import search_scenes, detect_water_change

    if location:
        coord = await _geocode_city(location)
        if coord:
            cx, cy = coord
            half = 0.05
            bbox = [cx - half, cy - half, cx + half, cy + half]
            logger.info(f"[water_change] Geocoded '{location}' -> ({cx:.4f}, {cy:.4f})")
    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        bbox = [104.85, 33.15, 105.05, 33.35]

    if date1 and len(date1) >= 7:
        y1, m1 = date1[:4], date1[5:7]
        range1_start = f"{y1}-{m1}-01"
        range1_end = f"{y1}-{m1}-28"
    else:
        range1_start, range1_end = "2024-06-01", "2024-07-31"

    if date2 and len(date2) >= 7:
        y2, m2 = date2[:4], date2[5:7]
        range2_start = f"{y2}-{m2}-01"
        range2_end = f"{y2}-{m2}-28"
    else:
        range2_start, range2_end = "2024-09-01", "2024-10-31"

    logger.info(f"[water_change] bbox={bbox} period1={range1_start}~{range1_end} period2={range2_start}~{range2_end}")
    scenes1 = await search_scenes(bbox, date_start=range1_start, date_end=range1_end, max_cloud=15)
    scenes2 = await search_scenes(bbox, date_start=range2_start, date_end=range2_end, max_cloud=15)

    if not scenes1:
        scenes1 = await search_scenes(bbox, date_start=range1_start, date_end=range1_end, max_cloud=30)
    if not scenes2:
        scenes2 = await search_scenes(bbox, date_start=range2_start, date_end=range2_end, max_cloud=30)

    if not scenes1 or not scenes2:
        return {"error": f"未找到足够低云量的Sentinel-2影像覆盖两个时期({range1_start[:7]} / {range2_start[:7]})，请尝试其他月份"}

    logger.info(f"[water_change] Period1: {scenes1[0]['date']} Period2: {scenes2[0]['date']}")
    result = detect_water_change(bbox, scenes1[0], scenes2[0])
    logger.info(f"[water_change] Done: {result['area1_km2']}->{result['area2_km2']}km2 ({result['change_pct']:+.1f}%)")
    return result


async def _simulate_flood_3d(bbox=None, location=None, rainfall_mm=100):
    import sys
    import numpy as np
    sys.path.insert(0, str(Path(__file__).parent))
    from flood_sim.engine import fetch_elevation_grid, simulate_flood_2d
    from segment.osm_buildings import fetch_osm_buildings, fetch_landuse, sample_cn_from_landuse

    if location:
        coord = await _geocode_city(location)
        if coord:
            cx, cy = coord
            half = 0.015
            bbox = [cx - half, cy - half, cx + half, cy + half]
            logger.info(f"[flood_sim_3d] Geocoded '{location}' -> ({cx:.4f}, {cy:.4f})")
    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        bbox = [105.72, 34.57, 105.75, 34.60]

    logger.info(f"[flood_sim_3d] bbox={bbox} rainfall={rainfall_mm}mm")

    elev_data = await fetch_elevation_grid(bbox, grid_n=40)

    try:
        buildings = await fetch_osm_buildings(bbox)
    except Exception:
        buildings = []

    osm_cn_grid = None
    try:
        landuse_polys = await fetch_landuse(bbox)
        if landuse_polys:
            grid_lats = np.linspace(bbox[1], bbox[3], elev_data["grid_n"]).tolist()
            grid_lons = np.linspace(bbox[0], bbox[2], elev_data.get("grid_m", elev_data["grid_n"])).tolist()
            osm_cn_grid = sample_cn_from_landuse(landuse_polys, grid_lats, grid_lons)
            logger.info(f"[flood_sim_3d] OSM landuse CN: {len(landuse_polys)} polygons sampled")
    except Exception as e:
        logger.warning(f"[flood_sim_3d] Landuse fetch failed: {e}")

    result = simulate_flood_2d(
        np.array(elev_data["grid"]),
        buildings,
        bbox,
        rainfall_mm=float(rainfall_mm or 100),
        osm_cn_grid=osm_cn_grid,
    )

    result["flood_sim_3d"] = True
    result["elevation_grid"] = elev_data["grid"]
    result["grid_n"] = elev_data["grid_n"]
    result["grid_lats"] = elev_data["lats"]
    result["grid_lons"] = elev_data["lons"]
    result["elev_range"] = [elev_data["min_elev"], elev_data["max_elev"]]
    result["bbox"] = bbox
    result["data_source"] = f"2D Hydrodynamic + {elev_data.get('source', 'DEM')}"
    result["location"] = location or ""

    logger.info(f"[flood_sim_3d] Done: {result['stats']['safe']}safe/{result['stats']['partial']}partial/{result['stats']['submerged']}submerged")

    global _last_flood_result, _last_flood_time, _last_flood_bbox
    _last_flood_result = result
    _last_flood_time = time.time()
    _last_flood_bbox = bbox
    return result


def _bbox_overlap(a: list[float], b: list[float]) -> bool:
    if not a or not b or len(a) != 4 or len(b) != 4:
        return False
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


async def _plan_drone_mission(bbox=None, location=None, mission_type="flood_inspect"):
    import sys
    import numpy as np
    sys.path.insert(0, str(Path(__file__).parent))
    from drone.mission import identify_risk_hotspots, plan_mission, MISSION_PROFILES

    if not bbox or len(bbox) != 4 or not all(isinstance(v, (int, float)) for v in bbox):
        if location:
            coord = await _geocode_city(location)
            if coord:
                cx, cy = coord
                half = 0.015
                bbox = [cx - half, cy - half, cx + half, cy + half]
        if not bbox:
            bbox = [105.71, 34.57, 105.74, 34.60]

    logger.info(f"[drone_mission] Planning {mission_type} for bbox={bbox}")

    flood_result = None
    global _last_flood_result, _last_flood_time, _last_flood_bbox
    if (_last_flood_result and _last_flood_bbox and
        time.time() - _last_flood_time < 300 and
        _bbox_overlap(_last_flood_bbox, bbox)):
        logger.info("[drone_mission] Reusing recent flood simulation result")
        flood_result = _last_flood_result
    else:
        try:
            logger.info("[drone_mission] Running flood simulation for risk assessment...")
            flood_result = await _simulate_flood_3d(bbox, location, 150)
            if "error" in flood_result:
                flood_result = None
        except Exception as e:
            logger.warning(f"[drone_mission] Flood sim failed: {e}")

    if flood_result and flood_result.get("building_impacts"):
        impacts = flood_result["building_impacts"]
        depth_frames = flood_result.get("depth_frames", [])
        if depth_frames:
            peak_idx = max(range(len(depth_frames)), key=lambda i: max(max(r) for r in depth_frames[i]) if depth_frames[i] else 0)
            depth_grid = depth_frames[peak_idx] if peak_idx < len(depth_frames) else depth_frames[-1]
        else:
            depth_grid = []

        grid_lats = flood_result.get("grid_lats", [])
        grid_lons = flood_result.get("grid_lons", [])

        hotspots = identify_risk_hotspots(impacts, depth_grid, grid_lats, grid_lons, bbox)
        logger.info(f"[drone_mission] Found {len(hotspots)} risk hotspots from flood sim")
    else:
        hotspots = _generate_default_waypoints(bbox, mission_type)

    result = plan_mission(hotspots, bbox, mission_type)
    result["flood_summary"] = {
        "rainfall_mm": flood_result.get("rainfall_mm") if flood_result else 0,
        "peak_depth_m": flood_result.get("stats", {}).get("peak_depth_m") if flood_result else 0,
        "flooded_pct": flood_result.get("stats", {}).get("max_flooded_area_pct") if flood_result else 0,
        "buildings_at_risk": (flood_result.get("stats", {}).get("partial", 0) + flood_result.get("stats", {}).get("submerged", 0)) if flood_result else 0,
    } if flood_result else None

    logger.info(f"[drone_mission] Done: {result['n_waypoints']} waypoints, {result['total_distance_km']}km, {result['estimated_flight_min']}min")
    return result


def _generate_default_waypoints(bbox, mission_type):
    import math
    west, south, east, north = bbox
    n = 8
    hotspots = []
    for i in range(n):
        angle = 2 * math.pi * i / n
        r = 0.3
        lat = (south + north) / 2 + r * (north - south) / 2 * math.sin(angle)
        lon = (west + east) / 2 + r * (east - west) / 2 * math.cos(angle)
        hotspots.append({"lat": lat, "lon": lon, "type": "survey", "risk_score": 5, "label": f"巡查点{i+1}"})
    return hotspots


class DigitalTwinBridge:
    def __init__(self):
        self.sources: dict[str, dict] = {}
        self.register("dem_lbh", "file", {"path": str(DATA_DIR / "LBH_DEM_v2_0.5m_EPSG4544.tif"), "description": "迭部县0.5m DEM"})
        self.register("weather_openmeteo", "api", {"url": "https://api.open-meteo.com/v1/forecast", "description": "Open-Meteo气象预报"})

    def register(self, name: str, src_type: str, config: dict):
        self.sources[name] = {"type": src_type, **config, "registered_at": time.time()}

    def list_sources(self) -> list[dict]:
        return [{"name": k, **v} for k, v in self.sources.items()]

    async def health_check(self) -> dict[str, str]:
        results = {}
        for name in self.sources:
            results[name] = "healthy" if self.sources[name]["type"] in ("file", "api") else "unknown"
        return results


_twin = DigitalTwinBridge()


# ── 9. Self-Evolving Prompt Optimizer ────────────────────────────────

_evolution_log: list[dict] = []
_evolution_counter = 0


def _log_routing(query: str, layer: str, tool: str, was_correct: bool):
    global _evolution_counter
    _evolution_counter += 1
    _evolution_log.append({"query": query[:100], "layer": layer, "tool": tool, "correct": was_correct, "ts": time.time()})
    if len(_evolution_log) > 1000:
        _evolution_log[:] = _evolution_log[-500:]


def _evolution_stats() -> dict:
    if not _evolution_log:
        return {"total": 0, "accuracy": 0}
    total = len(_evolution_log)
    correct = sum(1 for e in _evolution_log if e["correct"])
    by_layer: dict[str, dict] = {}
    for e in _evolution_log:
        l = e["layer"]
        if l not in by_layer:
            by_layer[l] = {"total": 0, "correct": 0}
        by_layer[l]["total"] += 1
        by_layer[l]["correct"] += 1 if e["correct"] else 0
    return {"total": total, "accuracy": round(correct / total, 3), "by_layer": by_layer}


def _evolution_suggestions() -> list[str]:
    suggestions = []
    l3_entries = [e for e in _evolution_log if e["layer"] == "L3"]
    if len(l3_entries) >= 5:
        for e in l3_entries[-10:]:
            if e["correct"]:
                suggestions.append(f"建议新增规则: \"{e['query'][:20]}\" → {e['tool']}")
    return suggestions[:5]


# ── 10. Tool Auto-Generation ─────────────────────────────────────────

GEN_TOOL_DIR = DATA_DIR / "generated_tools"
GEN_TOOL_DIR.mkdir(parents=True, exist_ok=True)


async def _generate_tool(query: str, fix_context: dict | None = None) -> dict | None:
    system_msg = """You are a code generator for a water resources spatial intelligence platform.
STRICT RULES:
1. Function signature MUST be: def compute_xxx(**kwargs)
2. Read params via kwargs.get('param_name', default_value), NEVER hardcode
3. Must fully implement the algorithm, NO "simplified"/"TODO"/"approximate"
4. GeoJSON polygons: coordinates must be [[lon,lat],[lon,lat]...], closed ring, NO NaN/Inf
5. For Voronoi: MUST filter out regions containing -1, MUST clip vertices to valid range
6. Output ONLY code, NO imports needed (math,json,np,scipy already available), NO explanation
7. NEVER use emoji or non-ASCII characters
8. CRITICAL: The return dict MUST use EXACTLY these lowercase keys at the TOP level:
   - "geojson": {"type":"FeatureCollection","features":[...]}
   - "points": [{"lat":float, "lng":float, "label":str}]
   - "data_points": [{"x":num, "y":num, "label":str}]
   - "table": [{"col1": val, ...}]
   - "chart_type": "bar" (optional)
   Do NOT nest these under uppercase keys like "GeoJSON" or "Points".
   CORRECT: return {"geojson": geojson_obj, "points": [...], "data_points": [...]}
   WRONG: return {"GeoJSON": {"geojson": geojson_obj}, "Points": {"points": [...]}}

Available: math, json, numpy(as np), scipy.spatial.Voronoi"""

    if fix_context:
        user_msg = (
            f"The following code has a bug, fix it.\n\n"
            f"REQUIREMENT: {query}\n\n"
            f"ORIGINAL CODE:\n```python\n{fix_context.get('code', '')}\n```\n\n"
            f"ERROR:\n{fix_context.get('error', '')}\n\n"
            f"TRACEBACK:\n{fix_context.get('traceback', '')}\n\n"
            f"Output the COMPLETE fixed function. Do NOT simplify or skip any logic."
        )
    else:
        user_msg = f"REQUIREMENT: {query}\n\nGenerate a compute_xxx function with **kwargs signature. Fully implement the algorithm with visualization fields. No simplification!"

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg}
    ]
    try:
        code, _, _ = await asyncio.wait_for(_call_llm(messages, model=MODEL_AIR, use_tools=False), timeout=25.0)
        code = re.sub(r'```python\s*', '', code)
        code = re.sub(r'```\s*', '', code)
        code = ''.join(char for char in code if ord(char) < 128 or char in '\n\r\t')
        fn_match = re.search(r'def\s+(\w+)\s*\(', code)
        if not fn_match:
            return None
        fn_name = fn_match.group(1)
        tool_file = GEN_TOOL_DIR / f"{fn_name}.py"
        tool_file.write_text(code, encoding="utf-8")
        TOOL_TO_SERVER[fn_name] = "generated"
        return {"tool_name": fn_name, "code": code[:500], "file": str(tool_file)}
    except Exception:
        return None
        fn_name = fn_match.group(1)
        tool_file = GEN_TOOL_DIR / f"{fn_name}.py"
        tool_file.write_text(code, encoding="utf-8")
        TOOL_TO_SERVER[fn_name] = "generated"
        return {"tool_name": fn_name, "code": code[:500], "file": str(tool_file)}
    except Exception:
        return None


# ── auto_tool 自修复机制 ──

_LAZY_PATTERNS = re.compile(
    r'简化[版]?'            # "简化版"
    r'|仅返回'              # "仅返回"
    r'|TODO|FIXME'          # 占位标记
    r'|实际需要.*更复杂'     # "实际需要更复杂的算法"
    r'|这里仅'              # "这里仅..."
    r'|简化处理'            # "简化处理"
    r'|省略了|略去'         # "省略了"
    , re.IGNORECASE
)

_GEOJSON_GEOM_TYPES = {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}


def _check_code_quality(code: str, query: str) -> list[str]:
    issues = []
    if _LAZY_PATTERNS.search(code):
        issues.append("代码包含简化/偷懒标记")
    fn_sig = re.search(r'def\s+\w+\s*\(([^)]*)\)', code)
    if fn_sig:
        params = fn_sig.group(1).strip()
        if params and not params.startswith('**'):
            issues.append(f"函数签名错误: 参数'{params}'应为**kwargs")
    has_return_geojson = '"geojson"' in code or "'geojson'" in code
    has_polygon_in_return = '"Polygon"' in code or "'Polygon'" in code
    wants_polygon = any(kw in query for kw in ["多边形", "polygon", "多边", "区域", "凸包", "voronoi", "泰森", "网格"])
    if wants_polygon and has_return_geojson and not has_polygon_in_return:
        issues.append("需求要求多边形但代码未生成Polygon几何体")
    wants_line = any(kw in query for kw in ["曲线", "线", "line", "路径", "流线", "螺旋"])
    has_linestring = '"LineString"' in code or "'LineString'" in code
    if wants_line and has_return_geojson and not has_linestring and not has_polygon_in_return:
        issues.append("需求要求线几何但代码未生成LineString")
    return issues


def _check_result_quality(result: dict, query: str) -> list[str]:
    """检查执行结果质量，返回问题列表"""
    issues = []
    if not isinstance(result, dict):
        return ["结果不是dict类型"]
    if "error" in result:
        issues.append(f"执行报错: {result['error'][:100]}")
    wants_polygon = any(kw in query for kw in ["多边形", "polygon", "多边", "凸包", "voronoi", "泰森", "网格"])
    if wants_polygon:
        gj = result.get("geojson")
        if gj and isinstance(gj, dict):
            features = gj.get("features", [])
            has_real_geom = any(
                f.get("geometry", {}).get("type") in _GEOJSON_GEOM_TYPES
                for f in features if isinstance(f, dict)
            )
            if not has_real_geom and len(features) > 0:
                issues.append("geojson中只有Point没有Polygon/LineString，未真正生成几何体")
    return issues


async def _generate_tool_with_retry(query: str, max_attempts: int = 5) -> tuple[dict | None, dict | None, list[str]]:
    logs = []
    fix_context = None
    for attempt in range(1, max_attempts + 1):
        logs.append(f"[attempt {attempt}/{max_attempts}]")
        gen = await _generate_tool(query, fix_context=fix_context)
        if not gen:
            logs.append("LLM returned no code")
            fix_context = {"error": "LLM did not return valid code", "code": "", "traceback": ""}
            continue

        full_code = ""
        tool_file = GEN_TOOL_DIR / f"{gen['tool_name']}.py"
        if tool_file.exists():
            full_code = tool_file.read_text(encoding="utf-8")

        code_issues = _check_code_quality(full_code, query)
        if code_issues:
            logs.append(f"code quality fail: {'; '.join(code_issues)}")
            fix_context = {"error": "; ".join(code_issues), "code": full_code, "traceback": ""}
            _delete_generated(gen["tool_name"])
            continue

        result = _exec_generated(gen["tool_name"], {})

        if isinstance(result, dict) and "error" in result:
            err_msg = result["error"]
            tb = result.get("traceback", "")
            logs.append(f"exec error: {err_msg[:120]}")
            fix_context = {"error": err_msg, "code": full_code, "traceback": tb}
            _delete_generated(gen["tool_name"])
            continue

        cleaned = _sanitize_geojson_result(result)
        if cleaned is not None:
            result = cleaned

        result_issues = _check_result_quality(result, query)
        if result_issues:
            logs.append(f"result quality fail: {'; '.join(result_issues)}")
            fix_context = {"error": "; ".join(result_issues), "code": full_code, "traceback": ""}
            _delete_generated(gen["tool_name"])
            continue

        logs.append(f"success on attempt {attempt}")
        return gen, result, logs

    logs.append(f"all {max_attempts} attempts failed")
    return None, None, logs


def _delete_generated(tool_name: str):
    f = GEN_TOOL_DIR / f"{tool_name}.py"
    if f.exists():
        f.unlink()
    TOOL_TO_SERVER.pop(tool_name, None)


def _sanitize_geojson_result(result: dict) -> dict | None:
    if not isinstance(result, dict) or "geojson" not in result:
        return None
    gj = result["geojson"]
    if not isinstance(gj, dict) or "features" not in gj:
        return None
    cleaned_features = []
    for f in gj["features"]:
        if not isinstance(f, dict) or "geometry" not in f:
            cleaned_features.append(f)
            continue
        geom = f["geometry"]
        gtype = geom.get("type", "")
        coords = geom.get("coordinates")
        if gtype in ("Polygon", "MultiPolygon") and coords:
            try:
                fixed = _fix_polygon_coords(coords)
                if fixed:
                    geom["coordinates"] = fixed
                    cleaned_features.append(f)
            except Exception:
                pass
        elif gtype in ("LineString", "MultiLineString") and coords:
            try:
                fixed = _fix_line_coords(coords)
                if fixed:
                    geom["coordinates"] = fixed
                    cleaned_features.append(f)
            except Exception:
                pass
        else:
            cleaned_features.append(f)
    gj["features"] = cleaned_features
    result["geojson"] = gj
    return result


def _fix_polygon_coords(rings):
    if not rings:
        return None
    fixed_rings = []
    for ring in rings:
        if not isinstance(ring, list):
            return None
        fixed_ring = []
        for pt in ring:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                return None
            try:
                lon = float(pt[0])
                lat = float(pt[1])
            except (TypeError, ValueError):
                return None
            if not (math.isfinite(lon) and math.isfinite(lat)):
                return None
            if abs(lon) > 180 or abs(lat) > 90:
                return None
            fixed_ring.append([lon, lat])
        if len(fixed_ring) < 3:
            return None
        if fixed_ring[0] != fixed_ring[-1]:
            fixed_ring.append(fixed_ring[0])
        fixed_rings.append(fixed_ring)
    return fixed_rings if fixed_rings else None


def _fix_line_coords(lines):
    if not lines:
        return None
    if isinstance(lines[0], (int, float)):
        pts = lines
        fixed = []
        for pt in pts:
            try:
                v = float(pt)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(v):
                return None
            fixed.append([v])
        return fixed
    fixed_lines = []
    for line in lines:
        if not isinstance(line, list):
            return None
        fixed = []
        for pt in line:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                return None
            try:
                lon = float(pt[0])
                lat = float(pt[1])
            except (TypeError, ValueError):
                return None
            if not (math.isfinite(lon) and math.isfinite(lat)):
                return None
            fixed.append([lon, lat])
        if len(fixed) >= 2:
            fixed_lines.append(fixed)
    return fixed_lines if fixed_lines else None


def _nativefy(obj):
    if isinstance(obj, dict):
        return {k: _nativefy(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_nativefy(i) for i in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return _nativefy(obj.tolist())
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0.0
    return obj


def _exec_generated(tool_name: str, args: dict) -> dict:
    tool_file = GEN_TOOL_DIR / f"{tool_name}.py"
    if not tool_file.exists():
        return {"error": f"Generated tool {tool_name} not found"}
    code = tool_file.read_text(encoding="utf-8")
    code = re.sub(r'def\s+(\w+)\s*\(\s*kwargs\s*\)', r'def \1(**kwargs)', code)
    code = re.sub(r'def\s+(\w+)\s*\(\s*\)', r'def \1(**kwargs)', code)
    if code != tool_file.read_text(encoding="utf-8"):
        tool_file.write_text(code, encoding="utf-8")
    _safe_builtins = {
        "range": range, "len": len, "int": int, "float": float, "str": str,
        "list": list, "dict": dict, "tuple": tuple, "set": set, "bool": bool,
        "abs": abs, "min": min, "max": max, "sum": sum, "round": round,
        "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
        "sorted": sorted, "reversed": reversed, "isinstance": isinstance,
        "print": print, "True": True, "False": False, "None": None,
        "__import__": __import__,
    }
    safe_globals = {"__builtins__": _safe_builtins, "math": math, "json": json, "np": np, "numpy": np, "scipy": __import__('scipy'), "Voronoi": _ScipyVoronoi}
    safe_locals: dict = {}
    try:
        exec(code, safe_globals, safe_locals)
        fn = safe_locals.get(tool_name)
        if not fn:
            return {"error": f"Function {tool_name} not found in generated code"}
        try:
            result = fn(**args)
        except TypeError:
            try:
                result = fn(args)
            except TypeError:
                result = fn()
        raw = result if isinstance(result, dict) else {"result": str(result)}
        return _nativefy(raw)
    except Exception as e:
        import traceback as tb
        full_trace = tb.format_exc()
        return {"error": f"{type(e).__name__}: {str(e)}", "traceback": full_trace, "failed_code": code}


# ── 11. Neuro-Symbolic Physics Validator ──────────────────────────────

class PhysicsValidator:
    @staticmethod
    def validate_manning(n: float, R: float, S: float) -> dict:
        V = (1.0 / n) * (R ** (2.0 / 3.0)) * (S ** 0.5) if n > 0 and R > 0 and S > 0 else 0
        warnings = []
        if not (0.01 <= n <= 0.30):
            warnings.append(f"糙率n={n:.3f}超出[0.01,0.30]")
        if V > 15:
            warnings.append(f"流速V={V:.2f}m/s超过15m/s")
        return {"velocity_ms": round(V, 4), "valid": len(warnings) == 0, "warnings": warnings}

    @staticmethod
    def validate_continuity(Q_in: float, Q_out: float, dS: float = 0) -> dict:
        residual = abs(Q_in - Q_out - dS)
        return {"residual": round(residual, 4), "balanced": residual < 0.01 * max(Q_in, 0.001)}

    @staticmethod
    def check_range(value: float, key: str) -> dict:
        rng = PHYSICS_RANGES.get(key)
        if not rng:
            return {"valid": True}
        lo, hi, label = rng
        ok = lo <= value <= hi
        return {"valid": ok, "value": value, "range": f"{lo}-{hi}", "label": label,
                "warning": "" if ok else f"{label}={value}超出范围[{lo},{hi}]"}


_physics = PhysicsValidator()


# ── 12. Satellite Remote Sensing (STAC) ──────────────────────────────

STUDY_BBOX = [104.83, 33.10, 104.95, 33.27]


async def _search_satellite(bbox: list[float] | None = None, date_start: str = "", date_end: str = "") -> dict:
    bbox = bbox or STUDY_BBOX
    datetime_str = f"{date_start}/{date_end}" if date_start and date_end else "2024-01-01/2026-06-07"
    url = "https://earth-search.aws.element84.com/v1/search"
    payload = {"bbox": bbox, "datetime": datetime_str, "collections": ["sentinel-2-l2a"], "limit": 5}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            features = []
            for f in data.get("features", [])[:5]:
                props = f.get("properties", {})
                features.append({
                    "id": f.get("id", ""), "datetime": props.get("datetime", ""),
                    "cloud_cover": props.get("eo:cloud_cover", "?"),
                    "bbox": f.get("bbox", []), "assets": list(f.get("assets", {}).keys())[:5]
                })
            return {"total": data.get("numberReturned", 0), "features": features}
    except Exception as e:
        return {"error": str(e)[:200]}


# ── 13. Spatial Knowledge Graph (SQLite) ──────────────────────────────

class SpatialKG:
    def __init__(self):
        self.db_path = DATA_DIR / "spatial_kg.db"
        self._init()

    def _init(self):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS entities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, type TEXT, properties TEXT);
                CREATE TABLE IF NOT EXISTS relations (id INTEGER PRIMARY KEY AUTOINCREMENT, from_name TEXT, relation TEXT, to_name TEXT, confidence REAL DEFAULT 1.0);
            """)
            for name, typ, props in [
                ("迭部县", "region", '{"lat":33.19,"lon":104.89}'),
                ("白龙江", "river", '{"length_km":500}'),
                ("DEM_LBH", "dataset", '{"resolution":"0.5m","size":"3GB","crs":"EPSG:4544"}'),
                ("研究区", "area", '{"elev_min":790,"elev_max":1800}'),
            ]:
                conn.execute("INSERT OR IGNORE INTO entities(name,type,properties) VALUES(?,?,?)", (name, typ, props))
            for fr, rel, to in [("迭部县", "contains", "白龙江"), ("DEM_LBH", "covers", "迭部县"), ("白龙江", "flows_through", "迭部县"), ("研究区", "located_in", "迭部县")]:
                conn.execute("INSERT OR IGNORE INTO relations(from_name,relation,to_name) VALUES(?,?,?)", (fr, rel, to))

    def query_entities(self, name_contains: str = "", entity_type: str = "") -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            sql = "SELECT name,type,properties FROM entities WHERE 1=1"
            params: list = []
            if name_contains:
                sql += " AND name LIKE ?"
                params.append(f"%{name_contains}%")
            if entity_type:
                sql += " AND type=?"
                params.append(entity_type)
            rows = conn.execute(sql + " LIMIT 20", params).fetchall()
        return [{"name": r[0], "type": r[1], "properties": r[2]} for r in rows]

    def query_relations(self, entity_name: str) -> list[dict]:
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT from_name,relation,to_name,confidence FROM relations WHERE from_name=? OR to_name=?",
                                (entity_name, entity_name)).fetchall()
        return [{"from": r[0], "relation": r[1], "to": r[2], "confidence": r[3]} for r in rows]

    def add_entity(self, name: str, typ: str, properties: str = "{}"):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("INSERT OR IGNORE INTO entities(name,type,properties) VALUES(?,?,?)", (name, typ, properties))

    def add_relation(self, fr: str, rel: str, to: str, confidence: float = 1.0):
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("INSERT INTO relations(from_name,relation,to_name,confidence) VALUES(?,?,?,?)", (fr, rel, to, confidence))


_kg = SpatialKG()


# ── 14. Spatial World Model ──────────────────────────────────────────

WORLD_MODEL_RULES = {
    "rainfall_runoff": {
        "water_balance": "降雨 = 径流 + 蒸发 + 下渗 + 蓄水变化",
        "scs_method": "Q = (P-0.2S)²/(P+0.2S), S=25400/CN-254",
        "time_of_concentration": "Tc = L^1.15 / (3600 * 14.56 * S^0.38)",
    },
    "flood_inundation": {
        "saint_venant": "连续方程 ∂h/∂t + ∂(uh)/∂x + ∂(vh)/∂y = S",
        "manning": "V = (1/n)*R^(2/3)*S^(1/2)",
        "flood_depth_limit": "洪水深度一般<30m, 流速<15m/s",
    },
    "terrain_analysis": {
        "d8_flow": "水流流向8邻域中高程最低的方向",
        "accumulation": "每个格子的汇流累积值=流入该格子的上游格子总数",
        "watershed": "流域边界=分水岭(水流方向向外的区域)",
    },
}


def _get_world_model_rules(scenario: str) -> list[str]:
    rules = WORLD_MODEL_RULES.get(scenario, {})
    return [f"{k}: {v}" for k, v in rules.items()]


def _validate_sim_params(params: dict, sim_type: str) -> dict:
    checks = []
    if sim_type == "hydrodynamic":
        if "duration_hours" in params:
            h = params["duration_hours"]
            checks.append({"param": "duration_hours", "valid": 0 < h <= 72, "warning": "" if 0 < h <= 72 else f"模拟时长{h}h超出合理范围"})
        if "grid_resolution_m" in params:
            r = params["grid_resolution_m"]
            checks.append({"param": "grid_resolution_m", "valid": 0.5 <= r <= 100, "warning": "" if 0.5 <= r <= 100 else f"网格分辨率{r}m不合理"})
    return {"sim_type": sim_type, "checks": checks, "all_valid": all(c["valid"] for c in checks)}


# ── 15. Add new tools to GLM_TOOLS + TOOL_TO_SERVER ──────────────────

GLM_TOOLS.extend([
    {"type": "function", "function": {"name": "weather_forecast", "description": "获取天气预报数据(温度、风速、湿度)，返回简单文本数据。注意：此工具不提供降雨过程动画，降雨相关查询请用precipitation_grid。", "parameters": {"type": "object", "properties": {"latitude": {"type": "number", "default": 33.19}, "longitude": {"type": "number", "default": 104.89}, "forecast_days": {"type": "integer", "default": 3}}, "required": []}}},
    {"type": "function", "function": {"name": "satellite_search", "description": "搜索卫星遥感影像(Sentinel-2)", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "[west,south,east,north]", "items": {"type": "number"}}, "date_start": {"type": "string", "description": "开始日期 YYYY-MM-DD"}, "date_end": {"type": "string", "description": "结束日期 YYYY-MM-DD"}}, "required": []}}},
    {"type": "function", "function": {"name": "spatial_knowledge_query", "description": "查询空间知识图谱(实体和关系)", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "查询关键词"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "scatter_interpolate", "description": "散点插值/克里金插值：将离散数据点插值为连续网格表面。支持克里金(Kriging)、IDW反距离加权、RBF径向基函数、linear/nearest/cubic方法。输入散点坐标和值，输出插值网格统计数据。", "parameters": {"type": "object", "properties": {"points_json": {"type": "string", "description": "散点JSON数组: [{\"x\":104.9,\"y\":33.15,\"z\":1200}, ...]"}, "method": {"type": "string", "description": "插值方法: kriging(克里金), idw(反距离), rbf(径向基), linear, nearest, cubic", "default": "linear"}, "grid_resolution": {"type": "integer", "description": "网格分辨率(NxN)", "default": 100}}, "required": []}}},
    {"type": "function", "function": {"name": "auto_tool", "description": "【最终兜底工具】自动生成并执行Python代码完成计算任务。当你发现现有工具无法满足用户需求时，必须调用此工具。适用场景：数学计算、公式推导、水力计算、水文分析、拟合统计、生成GeoJSON、绘制图表、表格计算、矩阵运算。不要输出代码文本，调用此工具即可自动执行。", "parameters": {"type": "object", "properties": {"requirement": {"type": "string", "description": "用户的完整需求描述，包含所有输入参数和期望输出格式"}, "params_json": {"type": "string", "description": "输入参数JSON，如{\"b\":2,\"h\":1.5,\"n\":0.015}"}}, "required": ["requirement"]}}},
    {"type": "function", "function": {"name": "reconstruct_3d", "description": "AI三维重建：从单张照片生成3D模型(GLB格式)。基于TripoSR大模型，单张照片秒出3D网格。适用场景：水工建筑物三维重建、堤防外观重建、桥梁结构建模、设备3D数字化。当用户上传图片并要求3D重建/三维建模时调用此工具。", "parameters": {"type": "object", "properties": {"image_path": {"type": "string", "description": "上传图片的文件路径（从对话上下文中的[上传图片路径:xxx]获取）"}}, "required": ["image_path"]}}},
    {"type": "function", "function": {"name": "precipitation_grid", "description": "气象网格降水分析：自动获取最近3天的公开气象降水数据(Open-Meteo)，生成区域逐小时降水网格动画热力图、面雨量过程线、暴雨中心定位。用户询问降水预报/降雨过程/降水分布/降雨网格/面雨量/暴雨分析时必须调用此工具，不要用weather_forecast。", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "[west,south,east,north]经纬度范围。仅当用户给出明确数值坐标时才填，否则留空。禁止编造坐标。", "items": {"type": "number"}}, "grid_size": {"type": "integer", "description": "网格密度(N×N)，默认8", "default": 8}, "location": {"type": "string", "description": "城市或地点名称，如'赤峰'、'陇南'、'天水'。当用户提到城市名时填此项。"}}, "required": []}}},
    {"type": "function", "function": {"name": "building_extract", "description": "AI建筑提取与3D建模：自动下载目标区域高清卫星影像，利用SAM大模型分割所有建筑物轮廓，估算建筑高度，生成3D拉伸白模叠到地图上。输出GeoJSON建筑 footprint + 高度数据。当用户要求建筑识别/建筑提取/建筑物识别/房子识别/地物提取/卫星建筑/3D城市建模时调用。注意：需要选择城市/城镇区域，山区农田没有建筑。", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "[west,south,east,north]经纬度范围。仅当用户给出明确数值坐标时才填，否则留空。禁止编造坐标。", "items": {"type": "number"}}, "location": {"type": "string", "description": "城市或地点名称，如'天水'、'兰州'、'西安'、'陇南'。当用户提到城市名时填此项。"}}, "required": []}}},
    {"type": "function", "function": {"name": "water_monitor", "description": "遥感水体监测：自动下载Sentinel-2卫星影像(10m分辨率)，计算NDWI水体指数，提取河湖水库水体范围。输出GeoJSON水体多边形+面积统计+覆盖率。当用户要求水体监测/水体识别/河湖监测/水面面积/水体变化/水体提取/NDWI时调用。支持任意区域。", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "[west,south,east,north]经纬度范围。仅当用户给出明确数值坐标时才填，否则留空。禁止编造坐标。", "items": {"type": "number"}}, "location": {"type": "string", "description": "地点名称，如'陇南'、'白龙江'、'天水'。"}}, "required": []}}},
    {"type": "function", "function": {"name": "flood_sim_3d", "description": "洪水淹没3D推演：自动获取地形高程+建筑轮廓，模拟降雨→径流→淹没过程，生成3D淹没动画(建筑逐栋被淹、水位上涨)。当用户要求洪水推演/淹没模拟/暴雨会不会淹/城市内涝模拟/3D洪水时调用。", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "[west,south,east,north]经纬度范围。仅当用户给出明确数值坐标时才填，否则留空。禁止编造坐标。", "items": {"type": "number"}}, "location": {"type": "string", "description": "城市或地点名称，如'天水'、'陇南'。"}, "rainfall_mm": {"type": "number", "description": "降雨量(mm)，默认100", "default": 100}, "return_period": {"type": "string", "description": "重现期，如'50年一遇'、'100年一遇'，默认空"}}, "required": []}}},
    {"type": "function", "function": {"name": "drone_mission", "description": "无人机航线自主规划：基于洪水推演结果自动识别风险热点，生成最优巡查航点(TSP路径优化)，输出航线+航点+KML文件。当用户要求无人机巡查/航线规划/飞行计划/航拍规划/无人机巡检/drone时调用。", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "[west,south,east,north]经纬度范围。仅当用户给出明确数值坐标时才填，否则留空。禁止编造坐标。", "items": {"type": "number"}}, "location": {"type": "string", "description": "城市或地点名称。"}, "mission_type": {"type": "string", "description": "任务类型: flood_inspect(洪水巡查), dam_inspect(堤坝巡检), search_rescue(搜救搜索), damage_assess(灾后评估)。默认flood_inspect。"}}, "required": []}}},
    {"type": "function", "function": {"name": "water_change", "description": "多期遥感水体变化检测：自动下载两个时期的Sentinel-2卫星影像，分别提取水体，逐像素对比变化。输出扩展区域(红)/缩减区域(绿)/面积变化百分比。当用户要求水体变化检测/水面变化/河湖变化/水库面积变化/多期对比/时序变化时调用。", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "[west,south,east,north]经纬度范围。仅当用户给出明确数值坐标时才填，否则留空。禁止编造坐标。", "items": {"type": "number"}}, "location": {"type": "string", "description": "地点名称，如'白龙江'、'陇南'。"}, "date1": {"type": "string", "description": "第一期对比月份，格式YYYY-MM，如'2024-06'。用户没说就留空。"}, "date2": {"type": "string", "description": "第二期对比月份，格式YYYY-MM，如'2024-10'。用户没说就留空。"}}, "required": []}}},
])

TOOL_TO_SERVER["weather_forecast"] = "internal"
TOOL_TO_SERVER["satellite_search"] = "internal"
TOOL_TO_SERVER["spatial_knowledge_query"] = "internal"
TOOL_TO_SERVER["auto_tool"] = "internal"
TOOL_TO_SERVER["reconstruct_3d"] = "internal"
TOOL_TO_SERVER["precipitation_grid"] = "internal"
TOOL_TO_SERVER["building_extract"] = "internal"
TOOL_TO_SERVER["water_monitor"] = "internal"
TOOL_TO_SERVER["flood_sim_3d"] = "internal"
TOOL_TO_SERVER["drone_mission"] = "internal"
TOOL_TO_SERVER["water_change"] = "internal"

ROUTING_RULES.extend([
    (r"天气预报|降雨预报|气象预报|查天气", "weather_forecast"),
    (r"卫星|遥感|Sentinel|Landsat|影像", "satellite_search"),
    (r"知识图谱|相关实体|空间实体", "spatial_knowledge_query"),
    (r"散点插值|插值|griddata|IDW|克里金|Kriging|反距离|空间插值", "scatter_interpolate"),
    (r"3D|三维|3d|重建|reconstruct|建模|立体", "reconstruct_3d"),
    (r"洪水推演|淹没模拟|暴雨.*淹|城市内涝|3D洪水|洪水3D|内涝模拟|会不会淹|淹没3D|洪水动画|内涝|涨水", "flood_sim_3d"),
    (r"无人机|航线|飞行计划|航拍|巡检|drone|uav|巡查航线|航线规划", "drone_mission"),
    (r"降水|降雨|雨量|面雨量|暴雨分析|precipitation|气象网格|降水监测|降水分析|降雨分析|降水分布|降雨分布|降水预报|降雨过程|降雨预报", "precipitation_grid"),
    (r"建筑识别|建筑提取|建筑物|建筑|房子识别|楼房|地物提取|卫星建筑|城市建模|建筑分割|building|建筑3D|建筑三维", "building_extract"),
    (r"水体变化检测|水面变化|河湖变化|水库面积变化|多期对比|时序变化|变化检测", "water_change"),
    (r"水体监测|水体识别|水体提取|河湖监测|水面面积|NDWI|水体分析|遥感水体|水域监测|水库监测", "water_monitor"),
])


# ── Internal tool handler ─────────────────────────────────────────────

def _normalize_auto_tool_result(result: dict) -> dict:
    viz_keys = {"geojson", "points", "data_points", "table", "chart_type", "image_base64", "time_series"}
    top_keys = set(str(k).lower() for k in result.keys())
    has_viz = bool(top_keys & viz_keys)
    if has_viz:
        return result
    flat = {}
    for k, v in result.items():
        if k.startswith("_"):
            flat[k] = v
            continue
        if isinstance(v, dict):
            for vk, vv in v.items():
                if vk.lower() in viz_keys or vk in viz_keys:
                    flat[vk] = vv
                else:
                    flat[f"{k}_{vk}"] = vv
        elif isinstance(v, list):
            flat[k.lower()] = v
        else:
            flat[k] = v
    return flat


async def _handle_internal_tool(tool_name: str, args: dict, user_msg: str = "") -> dict:
    if tool_name == "weather_forecast":
        return await _get_weather(args.get("latitude", 33.19), args.get("longitude", 104.89), args.get("forecast_days", 3))
    if tool_name == "satellite_search":
        return await _search_satellite(args.get("bbox"), args.get("date_start", ""), args.get("date_end", ""))
    if tool_name == "spatial_knowledge_query":
        q = args.get("query", "")
        entities = _kg.query_entities(name_contains=q)
        relations = []
        for e in entities[:3]:
            relations.extend(_kg.query_relations(e["name"]))
        return {"entities": entities, "relations": relations}
    if tool_name == "physics_check":
        return _physics.check_range(args.get("value", 0), args.get("param_key", ""))
    if tool_name == "auto_tool":
        requirement = args.get("requirement", "")
        params_json = args.get("params_json", "")
        if user_msg and len(user_msg) > len(requirement):
            requirement = f"{requirement}。用户原始请求: {user_msg}"
        gen, result, logs = await _generate_tool_with_retry(requirement, max_attempts=3)
        for log in logs:
            logger.info(f"[auto_tool] {log}")
        if not gen or not result:
            return {"error": f"工具生成失败(3次重试): {requirement[:80]}", "logs": logs}
        result["_generated_tool"] = gen["tool_name"]
        result["_generated_file"] = gen["file"]
        result = _normalize_auto_tool_result(result)
        return result
    if tool_name == "reconstruct_3d":
        import re as _re
        import threading as _threading
        from reconstruct.engine import create_task, get_task_status, _tasks
        image_path = args.get("image_path", "")
        if not image_path:
            return {"error": "缺少 image_path 参数，无法执行3D重建"}
        for pat in [r"\[上传图片路径:(.+?)\]", r"\[img:(.+?)\]"]:
            m = _re.search(pat, image_path)
            if m:
                image_path = m.group(1)
                break
        p = Path(image_path)
        if not p.exists() and not p.is_absolute():
            for candidate in [UPLOAD_IMG_DIR / p.name, UPLOAD_IMG_DIR / image_path, DATA_DIR / "uploads_img" / p.name]:
                if candidate.exists():
                    p = candidate
                    break
        image_path = str(p)
        if not p.exists():
            return {"error": f"图片文件不存在: {image_path}"}
        if not p.is_file():
            return {"error": f"路径不是文件: {image_path}"}
        eng = _get_recon_engine()
        task_id = create_task()
        done_evt = _threading.Event()
        run_err = [None]

        def _run_recon():
            try:
                eng.reconstruct_single(image_path, task_id)
            except Exception as e:
                run_err[0] = str(e)
                if task_id in _tasks:
                    _tasks[task_id]["error"] = str(e)
                    _tasks[task_id]["stage"] = "error"
            finally:
                done_evt.set()

        t = _threading.Thread(target=_run_recon, daemon=True)
        t.start()
        while not done_evt.is_set():
            await asyncio.sleep(1.5)
        status = get_task_status(task_id)
        if run_err[0] or status.get("error"):
            return {"error": run_err[0] or status.get("error", "unknown")}
        meta = status.get("meta", {})
        glb_url = f"/api/reconstruct/result/{task_id}"
        return {
            "recon_3d": True,
            "glb_url": glb_url,
            "task_id": task_id,
            "vertices": meta.get("vertices", 0),
            "faces": meta.get("faces", 0),
            "inference_time": meta.get("inference_time", 0),
            "total_time": meta.get("total_time", 0),
            "vram_peak_gb": meta.get("vram_peak_gb", 0),
            "message": f"3D重建完成: {meta.get('vertices', '?')}顶点, {meta.get('faces', '?')}面片, 耗时{meta.get('total_time', '?')}s",
        }
    if tool_name == "precipitation_grid":
        fc = any(k in user_msg for k in ["预报", "未来", "预测", "forecast", "未来几天", "未来三天", "未来一周"])
        return await _fetch_precipitation_grid(
            bbox=args.get("bbox"),
            grid_size=args.get("grid_size", 8),
            forecast_mode=fc,
            location=args.get("location", ""),
        )
    if tool_name == "building_extract":
        return await _extract_buildings(args.get("bbox"), args.get("location"))
    if tool_name == "water_monitor":
        return await _monitor_water(args.get("bbox"), args.get("location"))
    if tool_name == "water_change":
        return await _detect_water_change(args.get("bbox"), args.get("location"), args.get("date1", ""), args.get("date2", ""))
    if tool_name == "flood_sim_3d":
        return await _simulate_flood_3d(args.get("bbox"), args.get("location"), args.get("rainfall_mm", 100))
    if tool_name == "drone_mission":
        return await _plan_drone_mission(args.get("bbox"), args.get("location"), args.get("mission_type", "flood_inspect"))
    return {"error": f"Unknown internal tool: {tool_name}"}


# ═══════════════════════════════════════════════════════════════════════


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
        trace = _new_trace(message)
        yield _sse({"type": "start", "message": message})

        if message.startswith("[img:"):
            img_name = message[5:].strip().rstrip("]").strip()
            img_path = UPLOAD_IMG_DIR / img_name
            if img_path.exists():
                img_b64 = base64.b64encode(img_path.read_bytes()).decode()
                yield _sse({"type": "thinking_start", "agent": "vision", "label": "👁️ 图像分析"})
                analysis = await _analyze_image(img_b64)
                yield _sse({"type": "thinking", "agent": "vision", "content": analysis[:300]})
                yield _sse({"type": "thinking_end", "agent": "vision"})
                message = f"用户上传了图片({img_name})，AI分析结果: {analysis}\n[上传图片路径:{str(img_path)}]\n\n用户问题: {message.replace(f'[img:{img_name}]', '').strip() or '请根据图片分析结果进行水利相关分析'}"

        parsed_history = []
        if history:
            try:
                parsed_history = json.loads(history)
            except (json.JSONDecodeError, TypeError):
                pass

        memory_ctx = ""
        episodes = _memory.recall_episodes(message)
        facts = _memory.recall_facts()
        if facts or episodes:
            fact_str = "; ".join(f"{f['key']}={f['value']}" for f in facts[:5])
            ep_str = "; ".join(e["summary"][:60] for e in episodes[:2])
            memory_ctx = f"\n[记忆] 已知: {fact_str}\n历史: {ep_str}"
            yield _sse({"type": "memory_recall", "facts": facts[:5], "episodes": [{"summary": e["summary"][:100]} for e in episodes[:2]]})

        commonsense_ctx = _inject_commonsense(message)

        ui_force = _detect_ui_action(message)
        if ui_force:
            yield _sse({"type": "thinking_start", "agent": "react", "label": "🧠 自主推理"})
            yield _sse({"type": "thinking", "agent": "react", "content": f"检测到UI意图: {ui_force}"})
            yield _sse({"type": "thinking_end", "agent": "react"})
            yield _sse({"type": "ui_action", "action": ui_force, "args": {"action": ui_force}})
            labels = {"open_3d": "🛰️ 已为您打开三维地形查看器", "open_tin": "🔺 已生成TIN三角网", "open_quadtree": "🌳 已生成四叉树剖分"}
            async for ch in _stream_words(labels.get(ui_force, f"UI: {ui_force}")):
                yield _sse({"type": "text", "content": ch})
            yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": 0, "trace": trace.to_dict()})
            return

        yield _sse({"type": "thinking_start", "agent": "planner", "label": "📋 任务规划"})
        t_route_start = time.time()
        plan = await _route(message, parsed_history)
        trace.add("route", plan[:80], int((time.time() - t_route_start) * 1000))
        plan_upper = plan.strip().upper()
        is_simple = plan_upper.startswith("SIMPLE")
        is_direct = plan_upper.startswith("DIRECT:")
        direct_tool = plan.split(":", 1)[1].strip() if is_direct else ""
        if is_simple:
            yield _sse({"type": "thinking", "agent": "planner", "content": "简单查询，直接执行"})
        elif is_direct:
            yield _sse({"type": "thinking", "agent": "planner", "content": f"建议工具: {direct_tool}"})
        else:
            yield _sse({"type": "thinking", "agent": "planner", "content": f"📋 执行计划:\n{plan[:300]}"})
        yield _sse({"type": "thinking_end", "agent": "planner"})

        react_messages: list[dict] = [
            {"role": "system", "content": REACT_SYSTEM_PROMPT + memory_ctx + "\n" + commonsense_ctx},
            *parsed_history,
            {"role": "user", "content": message},
        ]
        if is_direct:
            react_messages.append({"role": "assistant", "content": f"请直接调用 {direct_tool} 工具完成此任务。这是一个专用工具，效果远优于 auto_tool。不要使用 auto_tool。"})
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

        react_max = 3 if is_simple else MAX_REACT_STEPS
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
                for line in reasoning.replace(chr(10), '\n').split('\n'):
                    line = line.strip()
                    if line:
                        yield _sse({"type": "thinking", "agent": "react", "content": f"💭 {line[:300]}"})
            else:
                yield _sse({"type": "thinking", "agent": "react", "content": "💭 分析用户请求..."})

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
                yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
                return

            if not tool_calls:
                yield _sse({"type": "thinking_end", "agent": "react"})
                async for ch in _stream_words("抱歉，我暂时无法处理您的请求。请描述具体的水利分析需求。"):
                    yield _sse({"type": "text", "content": ch})
                yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
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
                yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": step, "tools_called": total_tools, "trace": trace.to_dict()})
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
                yield _sse({"type": "thinking", "agent": "react", "content": f"🎯 决定调用: {tool_name}({args_summary})"})
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

            async def _exec_task(tc_id: str, tool_name: str, server: str, args: dict, user_msg: str) -> dict:
                t_tool = time.time()
                logger.debug(f"_exec_task: tool={tool_name}, server={server}, args_keys={list(args.keys())}")
                if server == "generated":
                    r = _exec_generated(tool_name, args)
                    if isinstance(r, dict) and "error" not in r:
                        quality_issues = _check_result_quality(r, user_msg)
                        if quality_issues:
                            logger.info(f"[generated] 质检不通过({'; '.join(quality_issues)})，删除旧文件重新生成")
                            _delete_generated(tool_name)
                            gen, r_new, _ = await _generate_tool_with_retry(f"用户需要: {user_msg} -> {tool_name}", max_attempts=2)
                            if gen and r_new:
                                r = r_new
                                r["_generated_tool"] = gen["tool_name"]
                            else:
                                r = {"error": f"重新生成失败: {quality_issues[0]}"}
                elif server == "internal":
                    r = await _handle_internal_tool(tool_name, args, user_msg)
                elif not server:
                    gen, r_try, _ = await _generate_tool_with_retry(f"用户需要: {user_msg} -> {tool_name}", max_attempts=2)
                    if gen and r_try:
                        r = r_try
                        r["_generated_tool"] = gen["tool_name"]
                    else:
                        r = {"error": f"Unknown tool: {tool_name}"}
                else:
                    r = await _cached_mcp_call(server, tool_name, args)
                trace.add(f"tool:{tool_name}", str(server), int((time.time() - t_tool) * 1000))
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
                if viz_parts:
                    yield _sse({"type": "thinking", "agent": "react", "content": f"📊 {tool_name} 返回结果包含: {' + '.join(viz_parts)}"})
                elif isinstance(result, dict) and "error" not in result:
                    yield _sse({"type": "thinking", "agent": "react", "content": f"✅ {tool_name} 执行成功，返回{len(result_keys)}个字段"})

                valid, validation_msg = _validate_result(tool_name, args, result if isinstance(result, dict) else {})
                if not valid:
                    yield _sse({"type": "thinking", "agent": "reflect", "content": f"🔍 反思: {tool_name}结果异常 — {validation_msg}"})
                    yield _sse({"type": "tool_error", "server": server, "tool": tool_name, "error": validation_msg})
                    result = {"error": f"验证失败: {validation_msg}", "original_keys": list(result.keys()) if isinstance(result, dict) else []}

                physics_warnings = _validate_physics(tool_name, result if isinstance(result, dict) else {})
                if physics_warnings:
                    yield _sse({"type": "thinking", "agent": "physics", "content": f"⚡ 物理校验: {'; '.join(physics_warnings)}"})

                if tool_name in CRITICAL_TOOLS and isinstance(result, dict) and "error" not in result:
                    debate = await _debate_validate(message, tool_name, result)
                    if not debate["consensus"]:
                        issues = [c.get("issue", "") for c in debate["critics"] if c.get("issue")]
                        yield _sse({"type": "debate", "critics": debate["critics"], "consensus": False})
                        yield _sse({"type": "thinking", "agent": "debate", "content": f"⚠️ 辩论未通过: {'; '.join(issues[:2])}"})
                    else:
                        yield _sse({"type": "debate", "critics": debate["critics"], "consensus": True})

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

            yield _sse({"type": "done", "duration_ms": int((time.time() - t_start) * 1000), "react_steps": react_max, "tools_called": total_tools, "trace": trace.to_dict()})

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
    if tool == "weather_forecast":
        hourly = result.get("hourly", {})
        times = hourly.get("time", [])
        precip = hourly.get("precipitation", [])
        total_precip = sum(p for p in precip if isinstance(p, (int, float)))
        return f"🌤️ 天气: {len(times)}小时预报, 总降水{total_precip:.1f}mm\n"
    if tool == "satellite_search":
        return f"🛰️ 卫星: {result.get('total', 0)}景影像\n"
    if tool == "spatial_knowledge_query":
        ents = result.get("entities", [])
        rels = result.get("relations", [])
        return f"🧠 知识图谱: {len(ents)}个实体, {len(rels)}条关系\n"
    if tool == "auto_tool":
        gen_name = result.get("_generated_tool", "unknown")
        return f"🤖 自动生成工具: {gen_name}\n"
    if "error" in result:
        return f"❌ 错误: {result['error']}\n"
    return f"⚙️ {server}.{tool}: {json.dumps(result, ensure_ascii=False)[:200]}\n"


@app.post("/api/upload_image")
async def upload_image(file: UploadFile = FastAPIFile(...)):
    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"):
        return {"error": f"Unsupported image format: {ext}"}
    ts = int(time.time() * 1000)
    dest = UPLOAD_IMG_DIR / f"{ts}_{file.filename}"
    content = await file.read()
    dest.write_bytes(content)
    return {"filename": dest.name, "size_bytes": len(content), "path": str(dest)}


@app.post("/api/analyze_image")
async def analyze_image_api(image_base64: str = "", file_path: str = ""):
    if file_path:
        import base64
        p = Path(file_path)
        if p.exists():
            image_base64 = base64.b64encode(p.read_bytes()).decode()
        else:
            return {"error": "File not found"}
    if not image_base64:
        return {"error": "Provide image_base64 or file_path"}
    result = await _analyze_image(image_base64)
    return {"analysis": result}


@app.get("/api/memory")
async def get_memory():
    facts = _memory.recall_facts()
    procedures = _memory.recall_procedures("", limit=10)
    return {"facts": facts, "procedures": procedures}


@app.get("/api/weather")
async def get_weather(lat: float = 33.19, lon: float = 104.89, days: int = 3):
    return await _get_weather(lat, lon, days)


@app.get("/api/satellite")
async def get_satellite(date_start: str = "", date_end: str = ""):
    return await _search_satellite(date_start=date_start, date_end=date_end)


@app.get("/api/kg/entities")
async def get_kg_entities(name: str = "", type: str = ""):
    return {"entities": _kg.query_entities(name, type)}


@app.get("/api/kg/relations")
async def get_kg_relations(entity: str = ""):
    return {"relations": _kg.query_relations(entity)}


@app.get("/api/twin/sources")
async def get_twin_sources():
    return {"sources": _twin.list_sources()}


@app.get("/api/twin/status")
async def get_twin_status():
    return {"status": await _twin.health_check()}


@app.get("/api/traces")
async def get_traces():
    return {"traces": [t.to_dict() for t in list(_traces.values())[-20:]]}


@app.get("/api/traces/{trace_id}")
async def get_trace(trace_id: str):
    t = _traces.get(trace_id)
    return t.to_dict() if t else {"error": "not found"}


@app.get("/api/evolution/stats")
async def get_evolution_stats():
    return _evolution_stats()


@app.get("/api/evolution/suggestions")
async def get_evolution_suggestions():
    return {"suggestions": _evolution_suggestions()}


# ─── 3D Reconstruction (TripoSR) ────────────────────────────────────────────
RECON_DIR = Path(__file__).parent / "reconstruct"
RECON_OUTPUTS = RECON_DIR / "outputs"
RECON_OUTPUTS.mkdir(parents=True, exist_ok=True)

_recon_engine = None
_recon_tasks: dict = {}

def _get_recon_engine():
    global _recon_engine
    if _recon_engine is None:
        import sys as _sys
        _recon_path = str(RECON_DIR)
        if _recon_path not in _sys.path:
            _sys.path.insert(0, _recon_path)
        from reconstruct.engine import ReconstructionEngine
        _recon_engine = ReconstructionEngine.get_instance()
    return _recon_engine


@app.post("/api/reconstruct/upload")
async def reconstruct_upload(file: UploadFile = FastAPIFile(...)):
    import uuid as _uuid, threading as _threading
    from reconstruct.engine import create_task, get_task_status, _tasks

    ext = Path(file.filename or "img.png").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"):
        return {"error": f"Unsupported format: {ext}"}

    task_id = create_task()
    task_dir = RECON_OUTPUTS / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    img_path = task_dir / f"input{ext}"
    content = await file.read()
    img_path.write_bytes(content)

    def _run():
        try:
            eng = _get_recon_engine()
            eng.reconstruct_single(str(img_path), task_id)
        except Exception as e:
            if task_id in _tasks:
                _tasks[task_id]["error"] = str(e)
                _tasks[task_id]["stage"] = "error"

    t = _threading.Thread(target=_run, daemon=True)
    t.start()

    return {"task_id": task_id}


@app.get("/api/reconstruct/status/{task_id}")
async def reconstruct_status(task_id: str):
    from reconstruct.engine import get_task_status
    status = get_task_status(task_id)
    return status


@app.get("/api/reconstruct/result/{task_id}")
async def reconstruct_result(task_id: str):
    from reconstruct.engine import get_task_status
    status = get_task_status(task_id)
    glb = status.get("output")
    if glb and Path(glb).exists():
        from starlette.responses import FileResponse
        return FileResponse(glb, media_type="model/gltf-binary",
                           filename=f"reconstruction_{task_id}.glb")
    return {"error": "Result not ready"}


@app.get("/api/reconstruct/preview/{task_id}")
async def reconstruct_preview(task_id: str):
    from reconstruct.engine import get_task_status
    status = get_task_status(task_id)
    meta = status.get("meta", {})
    return {
        "task_id": task_id,
        "stage": status.get("stage"),
        "progress": status.get("progress", 0),
        "meta": meta,
        "error": status.get("error"),
    }


# ─── End 3D Reconstruction ──────────────────────────────────────────────────


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
