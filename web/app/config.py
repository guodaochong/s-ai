"""Central configuration — API keys, model IDs, MCP endpoints, GLM tool schemas, routing rules.

All modules import constants and shared state from here.  Loaded once at import time
via dotenv from the project root ``.env`` file.

Author: jumpingbirds <guodaochong@gmail.com>
"""

from __future__ import annotations

import os
import structlog
from collections import OrderedDict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

structlog.configure(processors=[
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
    structlog.dev.ConsoleRenderer(),
])

logger = structlog.get_logger(__name__)

# ── API Keys & Endpoints ──
ZHIPUAI_API_KEY = os.getenv("ZHIPUAI_API_KEY", "")
GLM_API_URL = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
GLM_CODE_URL = "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"

# ── Models ──
MODEL_FLASH = "glm-4-flash-250414"
MODEL_AIR = "glm-4-air-250414"
MODEL_CODE = "glm-4-air-250414"
MODEL_VISION = "glm-4v-flash"

# ── Cache & Circuit Breaker ──
CACHE_MAX = 200
CACHE_TTL = 300
MAX_CONTEXT_CHARS = 16000
BREAKER_THRESHOLD = 3
BREAKER_COOLDOWN = 120

_tool_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_circuit_breaker: dict[str, tuple[int, float]] = {}
_last_cache_sweep: float = 0.0

# ── MCP Servers ──
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

TOOL_TO_SERVER: dict[str, str] = {}
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

# ── Internal tools (in-process handlers in dispatcher.py) ──
# Registered separately so _execute_single_tool() routes to the
# ``server == "internal"`` branch instead of falling through to
# the auto-generate fallback.  Must stay in sync with ``_DISPATCH``
# in ``app/dispatcher.py``.
for _t in (
    "weather_forecast", "satellite_search", "spatial_knowledge_query",
    "auto_tool", "reconstruct_3d", "precipitation_grid",
    "building_extract", "water_monitor", "water_change",
    "multi_agent_debate", "flood_sim_3d", "drone_mission",
):
    TOOL_TO_SERVER[_t] = "internal"

# ── Data Paths ──
DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
GEN_TOOL_DIR = DATA_DIR / "generated_tools"
GEN_TOOL_DIR.mkdir(parents=True, exist_ok=True)
RECON_DIR = Path(__file__).parent.parent / "reconstruct"
RECON_OUTPUTS = RECON_DIR / "outputs"
UPLOAD_IMG_DIR = DATA_DIR / "uploads_img"
UPLOAD_IMG_DIR.mkdir(parents=True, exist_ok=True)

# ── Study Area ──
STUDY_BBOX = [104.83, 33.10, 104.95, 33.27]

# ── Critical Tools (need debate validation) ──
CRITICAL_TOOLS = {"hydrodynamic_2d_sim", "flood_assessment", "flood_risk_zones", "swmm_simulate", "flood_inundation_map"}

# ── GLM Tool Definitions ──
GLM_TOOLS = [
    {"type": "function", "function": {"name": "get_parameter", "description": "查询水利参数表(manning_n糙率/scs_cn曲线数/design_storm暴雨/pipe_specs管材/pump_specs水泵/lid_design海绵/drainage_design排水标准)", "parameters": {"type": "object", "properties": {"parameter_name": {"type": "string", "description": "参数表名: manning_n, scs_cn, design_storm, pipe_specs, pump_specs, lid_design, drainage_design"}, "conditions": {"type": "object", "description": "过滤条件, 如 {\"surface\": \"混凝土管道\"} 或 {\"city\": \"成都\"}", "properties": {}}, "required": ["parameter_name"]}}}},
    {"type": "function", "function": {"name": "search", "description": "知识库语义搜索", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "搜索关键词"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "get_standard", "description": "查询水利标准规范", "parameters": {"type": "object", "properties": {"standard_id": {"type": "string", "description": "标准编号如 GB50014"}, "keyword": {"type": "string", "description": "关键词搜索"}}, "required": ["standard_id"]}}},
    {"type": "function", "function": {"name": "explain_concept", "description": "解释水利专业概念(水文/水力/排水/防洪)", "parameters": {"type": "object", "properties": {"concept": {"type": "string", "description": "概念名称, 如'曼宁公式'、'SCS-CN'、'设计暴雨'"}, "detail_level": {"type": "string", "enum": ["brief", "detailed", "technical"], "description": "详细程度", "default": "detailed"}}, "required": ["concept"]}}},
    {"type": "function", "function": {"name": "spatial_query", "description": "空间关系查询(intersects/contains/within/touches/crosses等)", "parameters": {"type": "object", "properties": {"geometry_a": {"type": "object", "description": "GeoJSON geometry"}, "geometry_b": {"type": "object", "description": "GeoJSON geometry"}, "relation": {"type": "string", "enum": ["intersects", "contains", "within", "touches", "crosses", "overlaps", "equals", "disjoint"], "default": "intersects"}}, "required": ["geometry_a", "geometry_b"]}}},
    {"type": "function", "function": {"name": "buffer", "description": "创建几何缓冲区", "parameters": {"type": "object", "properties": {"geometry": {"type": "object", "description": "GeoJSON geometry"}, "distance": {"type": "number", "description": "缓冲距离(米)"}, "unit": {"type": "string", "default": "meters"}}, "required": ["geometry"]}}},
    {"type": "function", "function": {"name": "overlay", "description": "叠加分析(intersection/union/difference/symmetric_difference)", "parameters": {"type": "object", "properties": {"geometry_a": {"type": "object", "description": "GeoJSON geometry"}, "geometry_b": {"type": "object", "description": "GeoJSON geometry"}, "operation": {"type": "string", "enum": ["intersection", "union", "difference", "symmetric_difference"], "default": "intersection"}}, "required": ["geometry_a", "geometry_b"]}}},
    {"type": "function", "function": {"name": "coordinate_transform", "description": "坐标转换", "parameters": {"type": "object", "properties": {"coordinates": {"type": "array", "description": "坐标数组", "items": {"type": "number"}}, "from_crs": {"type": "string", "description": "源坐标系EPSG代码"}, "to_crs": {"type": "string", "description": "目标坐标系EPSG代码"}}, "required": ["coordinates", "from_crs", "to_crs"]}}},
    {"type": "function", "function": {"name": "geometry_properties", "description": "几何属性计算(面积/周长/质心)", "parameters": {"type": "object", "properties": {"geometry": {"type": "object", "description": "GeoJSON geometry"}}, "required": ["geometry"]}}},
    {"type": "function", "function": {"name": "validate_data", "description": "数据质量检查", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "待检查数据"}, "rules": {"type": "array", "description": "检查规则列表"}}, "required": ["data"]}}},
    {"type": "function", "function": {"name": "hydrodynamic_2d_sim", "description": "二维水动力淹没模拟(专业级)", "parameters": {"type": "object", "properties": {"boundary_geojson": {"type": "object", "description": "模拟区域GeoJSON Polygon"}, "inflow_cms": {"type": "number", "description": "入流(m³/s)"}, "duration_hours": {"type": "number", "description": "模拟时长(h)", "default": 6}, "grid_resolution_m": {"type": "number", "description": "网格分辨率(m)", "default": 5}, "mannings_n": {"type": "number", "description": "曼宁糙率", "default": 0.035}, "initial_depth_m": {"type": "number", "description": "初始水深(m)", "default": 0}}, "required": ["boundary_geojson", "inflow_cms"]}}},
    {"type": "function", "function": {"name": "drainage_assessment", "description": "排水管道能力校核(Manning公式)", "parameters": {"type": "object", "properties": {"pipe_diameter_m": {"type": "number", "description": "管径(米)"}, "pipe_slope": {"type": "number", "description": "管道坡度"}, "manning_n": {"type": "number", "description": "曼宁糙率(0.01-0.03)"}, "design_flow_cms": {"type": "number", "description": "设计流量(m³/s)"}}, "required": ["pipe_diameter_m", "pipe_slope"]}}},
    {"type": "function", "function": {"name": "dem_analyze", "description": "DEM地形分析(坡度/坡向/汇流方向统计)", "parameters": {"type": "object", "properties": {"compute_slope": {"type": "boolean", "description": "计算坡度", "default": True}, "compute_aspect": {"type": "boolean", "description": "计算坡向", "default": True}, "compute_flowdir": {"type": "boolean", "description": "计算汇流方向", "default": True}}, "required": []}}},
    {"type": "function", "function": {"name": "terrain_profile", "description": "地形剖面线分析(两点间高程变化)", "parameters": {"type": "object", "properties": {"start_lng": {"type": "number", "description": "起点经度"}, "start_lat": {"type": "number", "description": "起点纬度"}, "end_lng": {"type": "number", "description": "终点经度"}, "end_lat": {"type": "number", "description": "终点纬度"}}, "required": ["start_lng", "start_lat", "end_lng", "end_lat"]}}},
    {"type": "function", "function": {"name": "point_query", "description": "地图点位查询(高程/坡度/坡向/曲率/TPI)", "parameters": {"type": "object", "properties": {"lng": {"type": "number", "description": "经度"}, "lat": {"type": "number", "description": "纬度"}}, "required": ["lng", "lat"]}}},
]

GLM_TOOLS.extend([
    {"type": "function", "function": {"name": "weather_forecast", "description": "天气预报：获取逐日温度、风速、降水摘要数据(不含过程动画)", "parameters": {"type": "object", "properties": {"latitude": {"type": "number", "default": 33.19}, "longitude": {"type": "number", "default": 104.89}, "forecast_days": {"type": "integer", "default": 3}}, "required": []}}},
    {"type": "function", "function": {"name": "satellite_search", "description": "搜索卫星遥感影像(Sentinel-2)", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "[west,south,east,north]", "items": {"type": "number"}}, "date_start": {"type": "string", "description": "开始日期 YYYY-MM-DD"}, "date_end": {"type": "string", "description": "结束日期 YYYY-MM-DD"}}, "required": []}}},
    {"type": "function", "function": {"name": "spatial_knowledge_query", "description": "查询空间知识图谱(实体和关系)", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "查询关键词"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "scatter_interpolate", "description": "散点插值/克里金插值", "parameters": {"type": "object", "properties": {"points_json": {"type": "string", "description": "散点JSON数组"}, "method": {"type": "string", "description": "插值方法", "default": "linear"}, "grid_resolution": {"type": "integer", "description": "网格分辨率(NxN)", "default": 100}}, "required": []}}},
    {"type": "function", "function": {"name": "auto_tool", "description": "【最终兜底工具】自动生成并执行Python代码完成计算任务", "parameters": {"type": "object", "properties": {"requirement": {"type": "string", "description": "用户的完整需求描述"}}, "required": ["requirement"]}}},
    {"type": "function", "function": {"name": "reconstruct_3d", "description": "AI三维重建：从单张照片生成3D模型(GLB格式)，基于TripoSR", "parameters": {"type": "object", "properties": {"image_path": {"type": "string", "description": "上传图片的文件路径"}}, "required": ["image_path"]}}},
    {"type": "function", "function": {"name": "precipitation_grid", "description": "降水过程分析：获取逐小时降水网格数据，生成降雨过程热力图动画和面雨量过程线。用户问降雨过程/降水预报/面雨量/暴雨分析时用此工具", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "[west,south,east,north]经纬度范围", "items": {"type": "number"}}, "grid_size": {"type": "integer", "default": 8}, "forecast_mode": {"type": "boolean", "default": False}, "location": {"type": "string", "description": "地名(自动地理编码)"}}, "required": []}}},
    {"type": "function", "function": {"name": "building_extract", "description": "建筑物提取。用location传地名，系统自动定位", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "仅当用户给出明确坐标时填", "items": {"type": "number"}}, "location": {"type": "string", "description": "地名"}}, "required": ["location"]}}},
    {"type": "function", "function": {"name": "water_monitor", "description": "水体监测。用location传地名，系统自动定位", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "仅当用户给出明确坐标时填", "items": {"type": "number"}}, "location": {"type": "string", "description": "地名"}}, "required": ["location"]}}},
    {"type": "function", "function": {"name": "water_change", "description": "水体变化检测。用location传地名，系统自动定位", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "仅当用户给出明确坐标时填", "items": {"type": "number"}}, "location": {"type": "string", "description": "地名"}, "date1": {"type": "string", "description": "第一期 YYYY-MM"}, "date2": {"type": "string", "description": "第二期 YYYY-MM"}}, "required": ["location"]}}},
    {"type": "function", "function": {"name": "flood_sim_3d", "description": "3D洪水模拟。用location传地名(如天水市)，系统自动定位。不要自己编bbox坐标", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "仅当用户给出明确数值坐标时填", "items": {"type": "number"}}, "location": {"type": "string", "description": "地名，如天水市、白龙江"}, "rainfall_mm": {"type": "number", "default": 100}}, "required": ["location"]}}},
    {"type": "function", "function": {"name": "drone_mission", "description": "无人机航线规划。用location传地名，系统自动定位", "parameters": {"type": "object", "properties": {"bbox": {"type": "array", "description": "仅当用户给出明确坐标时填", "items": {"type": "number"}}, "location": {"type": "string", "description": "地名"}, "mission_type": {"type": "string", "default": "flood_inspect"}}, "required": ["location"]}}},
    {"type": "function", "function": {"name": "multi_agent_debate", "description": "多智能体辩论：多个AI专家从不同角度分析问题并综合结论", "parameters": {"type": "object", "properties": {"requirement": {"type": "string", "description": "辩论主题/场景描述"}}, "required": ["requirement"]}}},
])

GLM_TOOLS.extend([
    {"type": "function", "function": {"name": "design_storm", "description": "设计暴雨雨型生成：基于城市暴雨强度公式生成设计暴雨过程线", "parameters": {"type": "object", "properties": {"return_period": {"type": "integer", "description": "重现期(年)", "default": 50}, "duration_minutes": {"type": "integer", "description": "降雨历时(分钟)", "default": 120}, "time_step_minutes": {"type": "integer", "description": "时间步长(分钟)", "default": 5}, "city": {"type": "string", "description": "城市(beijing/shanghai/shenzhen/guangzhou/chengdu)", "default": "beijing"}}, "required": []}}},
    {"type": "function", "function": {"name": "runoff_compute", "description": "SCS-CN径流计算：根据降雨量和曲线数计算径流量", "parameters": {"type": "object", "properties": {"rainfall_mm": {"type": "number", "description": "降雨量(mm)"}, "curve_number": {"type": "integer", "description": "SCS曲线数CN(30-100)", "default": 75}, "drainage_area_ha": {"type": "number", "description": "汇水面积(公顷)"}, "method": {"type": "string", "default": "scs_cn"}}, "required": ["rainfall_mm"]}}},
    {"type": "function", "function": {"name": "swmm_create_model", "description": "创建SWMM排水管网模型", "parameters": {"type": "object", "properties": {"project_name": {"type": "string", "default": "sai_demo"}, "area_hectares": {"type": "number", "description": "汇水面积(公顷)"}, "slope_percent": {"type": "number", "description": "坡度(%)", "default": 0.5}, "impervious_percent": {"type": "number", "description": "不透水率(%)", "default": 60}, "pipe_diameter_m": {"type": "number", "description": "管径(m)", "default": 0.8}, "pipe_length_m": {"type": "number", "description": "管长(m)", "default": 500}, "n_subcatchments": {"type": "integer", "description": "子汇水区数", "default": 4}}, "required": []}}},
    {"type": "function", "function": {"name": "swmm_simulate", "description": "运行SWMM模拟：输入降雨条件执行排水管网水力模拟", "parameters": {"type": "object", "properties": {"project_name": {"type": "string", "default": "sai_demo"}, "rainfall_mm_hr": {"type": "number", "description": "降雨强度(mm/h)", "default": 80}, "duration_min": {"type": "integer", "description": "降雨历时(分钟)", "default": 120}}, "required": []}}},
    {"type": "function", "function": {"name": "calibrate_suggest", "description": "模型率定建议：根据实测与模拟对比给出参数调整方向", "parameters": {"type": "object", "properties": {"observed_peak_flow": {"type": "number", "description": "实测洪峰流量(m³/s)"}, "simulated_peak_flow": {"type": "number", "description": "模拟洪峰流量(m³/s)"}, "nash_sutcliffe": {"type": "number", "description": "Nash-Sutcliffe效率系数"}}, "required": ["observed_peak_flow", "simulated_peak_flow"]}}},
    {"type": "function", "function": {"name": "render_map", "description": "渲染静态地图：从GeoJSON图层生成地图图片", "parameters": {"type": "object", "properties": {"layers": {"type": "array", "description": "图层列表[{data:GeoJSON, style:{}}]"}, "title": {"type": "string", "default": "Map"}, "width": {"type": "integer", "default": 1200}, "height": {"type": "integer", "default": 800}}, "required": ["layers"]}}},
    {"type": "function", "function": {"name": "create_choropleth", "description": "创建专题 choropleth 地图(分级填色)", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "FeatureCollection with properties"}, "value_field": {"type": "string", "description": "数值字段名"}, "classification": {"type": "string", "default": "quantiles"}, "num_classes": {"type": "integer", "default": 5}, "colormap": {"type": "string", "default": "YlOrRd"}}, "required": ["data", "value_field"]}}},
    {"type": "function", "function": {"name": "plot_timeseries", "description": "绘制时间序列图(水位/流量/降雨等)", "parameters": {"type": "object", "properties": {"data": {"type": "array", "description": "数据点[{time, value}]"}, "label": {"type": "string", "default": "Value"}, "ylabel": {"type": "string", "default": "Value"}, "title": {"type": "string", "default": "Time Series"}}, "required": ["data"]}}},
    {"type": "function", "function": {"name": "export_geojson", "description": "导出数据为GeoJSON格式", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "FeatureCollection"}, "properties_to_include": {"type": "array", "description": "要保留的属性字段", "items": {"type": "string"}}}, "required": ["data"]}}},
    {"type": "function", "function": {"name": "flood_assessment", "description": "洪水风险评估：综合降雨/面积/不透水率/管道能力评估内涝风险等级", "parameters": {"type": "object", "properties": {"area_name": {"type": "string", "description": "区域名称"}, "rainfall_mm": {"type": "number", "description": "降雨量(mm)"}, "drainage_area_ha": {"type": "number", "description": "排水面积(公顷)"}, "impervious_pct": {"type": "number", "description": "不透水率(%)", "default": 65}, "pipe_capacity_cms": {"type": "number", "description": "管道排水能力(m³/s)", "default": 2.0}}, "required": ["rainfall_mm"]}}},
    {"type": "function", "function": {"name": "flood_inundation_map", "description": "生成洪水淹没范围地图(GeoJSON多边形环)", "parameters": {"type": "object", "properties": {"center_lng": {"type": "number", "description": "中心经度"}, "center_lat": {"type": "number", "description": "中心纬度"}, "radius_m": {"type": "number", "description": "影响半径(m)", "default": 2000}, "max_depth_m": {"type": "number", "description": "最大水深(m)", "default": 0.5}, "rainfall_mm": {"type": "number", "description": "降雨量(mm)", "default": 100}}, "required": ["center_lng", "center_lat"]}}},
    {"type": "function", "function": {"name": "flood_warning", "description": "洪水预警生成：基于实时和预报降雨给出预警等级和行动建议", "parameters": {"type": "object", "properties": {"area_name": {"type": "string", "description": "区域名称"}, "current_rainfall_mm_hr": {"type": "number", "description": "当前降雨强度(mm/h)"}, "forecast_rainfall_mm_hr": {"type": "number", "description": "预报降雨强度(mm/h)"}, "soil_saturation_pct": {"type": "number", "description": "土壤饱和度(%)", "default": 70}, "drainage_utilization_pct": {"type": "number", "description": "排水设施利用率(%)", "default": 85}}, "required": ["current_rainfall_mm_hr", "forecast_rainfall_mm_hr"]}}},
    {"type": "function", "function": {"name": "flood_risk_zones", "description": "洪水风险分区：按人口密度和基础设施密度划分风险等级区域", "parameters": {"type": "object", "properties": {"population_density": {"type": "number", "description": "人口密度(人/km²)", "default": 5000}, "infrastructure_density": {"type": "number", "description": "基础设施密度(0-1)", "default": 0.3}}, "required": []}}},
    {"type": "function", "function": {"name": "flow_accumulation", "description": "水流累积计算与河网提取：从DEM计算流向累积量并提取河流网络", "parameters": {"type": "object", "properties": {"threshold_cells": {"type": "integer", "description": "河网提取阈值(像元数)", "default": 100}}, "required": []}}},
    {"type": "function", "function": {"name": "watershed_delineate", "description": "流域划分：从出口点划定汇水区边界", "parameters": {"type": "object", "properties": {"outlet_lng": {"type": "number", "description": "出口经度"}, "outlet_lat": {"type": "number", "description": "出口纬度"}, "snap_distance_m": {"type": "number", "description": "吸附距离(m)", "default": 50}}, "required": ["outlet_lng", "outlet_lat"]}}},
    {"type": "function", "function": {"name": "tin_generate", "description": "TIN三角网生成：从DEM生成不规则三角网(坡度自适应加密)", "parameters": {"type": "object", "properties": {"lng_min": {"type": "number", "description": "最小经度"}, "lng_max": {"type": "number", "description": "最大经度"}, "lat_min": {"type": "number", "description": "最小纬度"}, "lat_max": {"type": "number", "description": "最大纬度"}, "max_points": {"type": "integer", "description": "最大点数", "default": 1500}, "refine_steep": {"type": "boolean", "description": "陡坡区域加密", "default": True}}, "required": ["lng_min", "lng_max", "lat_min", "lat_max"]}}},
    {"type": "function", "function": {"name": "quadtree_subdivide", "description": "四叉树自适应网格细分：基于高程方差对DEM进行嵌套剖分", "parameters": {"type": "object", "properties": {"lng_min": {"type": "number"}, "lng_max": {"type": "number"}, "lat_min": {"type": "number"}, "lat_max": {"type": "number"}, "max_depth": {"type": "integer", "default": 4}, "variance_threshold": {"type": "number", "default": 50}}, "required": ["lng_min", "lng_max", "lat_min", "lat_max"]}}},
    {"type": "function", "function": {"name": "dem_render", "description": "DEM渲染：生成山体阴影图和等高线叠加", "parameters": {"type": "object", "properties": {"contour_interval": {"type": "number", "description": "等高线间距(m)", "default": 20}}, "required": []}}},
    {"type": "function", "function": {"name": "import_data", "description": "导入空间数据到PostGIS数据库", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "FeatureCollection GeoJSON"}, "table_name": {"type": "string", "description": "目标表名"}, "srid": {"type": "integer", "default": 4490}, "overwrite": {"type": "boolean", "default": False}}, "required": ["data", "table_name"]}}},
    {"type": "function", "function": {"name": "query_spatial", "description": "执行空间SQL查询(仅SELECT)", "parameters": {"type": "object", "properties": {"sql": {"type": "string", "description": "SQL查询语句"}, "params": {"type": "object", "description": "查询参数绑定"}}, "required": ["sql"]}}},
    {"type": "function", "function": {"name": "query_by_geometry", "description": "按几何条件查询空间数据", "parameters": {"type": "object", "properties": {"table_name": {"type": "string", "description": "表名"}, "geometry": {"type": "object", "description": "GeoJSON geometry"}, "relation": {"type": "string", "default": "intersects"}, "limit": {"type": "integer", "default": 100}}, "required": ["table_name", "geometry"]}}},
    {"type": "function", "function": {"name": "list_tables", "description": "列出数据库中所有空间数据表", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "read_vector", "description": "读取矢量文件(GeoJSON/Shapefile/GeoPackage)", "parameters": {"type": "object", "properties": {"file_path": {"type": "string", "description": "文件路径"}, "layer": {"type": "string", "description": "图层名(多图层文件)"}, "bbox": {"type": "array", "description": "范围过滤[minx,miny,maxx,maxy]", "items": {"type": "number"}}, "where": {"type": "string", "description": "属性筛选SQL"}}, "required": ["file_path"]}}},
    {"type": "function", "function": {"name": "write_vector", "description": "写出矢量文件", "parameters": {"type": "object", "properties": {"data": {"type": "object", "description": "FeatureCollection GeoJSON"}, "file_path": {"type": "string", "description": "输出路径"}, "driver": {"type": "string", "default": "GeoJSON"}, "layer": {"type": "string"}}, "required": ["data", "file_path"]}}},
    {"type": "function", "function": {"name": "import_network", "description": "导入排水管网数据(自动识别节点/管段)", "parameters": {"type": "object", "properties": {"file_path": {"type": "string", "description": "管网数据文件路径"}, "file_name": {"type": "string", "description": "文件名(替代path)"}, "network_type": {"type": "string", "default": "auto"}}, "required": []}}},
])

# ── ReAct System Prompt ──
REACT_SYSTEM_PROMPT = """你是 S-AI 水利空间智能体，专业水利工程师和空间分析师。

工具选择参考：
- 暴雨/洪水/淹没/会不会淹/内涝 → flood_sim_3d
- 降雨过程/降水/面雨量/暴雨分析 → precipitation_grid
- 天气/温度/风速(逐日摘要) → weather_forecast
- 卫星/遥感影像 → satellite_search
- DEM/地形/坡度分析 → dem_analyze
- 点位高程查询 → point_query
- 设计暴雨/暴雨强度公式 → design_storm
- SCS-CN/径流系数/产汇流 → runoff_compute
- SWMM/排水管网 → swmm_simulate
- 缓冲区/周边范围 → buffer
- 空间叠加/交集 → overlay
- 坐标转换 → coordinate_transform
- 知识库/资料搜索 → search
- 规范标准查询 → get_standard
- 概念解释 → explain_concept
- 参数查询(糙率/CN/管材) → get_parameter
- 克里金/IDW插值 → scatter_interpolate
- 建筑提取 → building_extract
- 水体监测 → water_monitor
- 无人机航线 → drone_mission
- 3D重建 → reconstruct_3d
- 渲染地图/出图 → render_map
- 计算/公式/拟合/生成图形 → auto_tool

规则：
- 涉及分析/模拟/计算的请求必须调工具，不能直接回复文字
- 参数从用户消息中原样提取实际值，禁止猜测或替换地名、坐标、数值
- location参数必须使用用户提到的原始地名，不要替换为其他城市
- bbox参数仅在用户明确给出坐标范围时填写，否则留空让工具自动地理编码
- 工具返回错误时调整参数重试
- 禁止输出Python代码，只能调工具"""

# ── Routing Rules ──
ROUTING_RULES: list[tuple[str, str]] = [
    (r"水动力|淹没模拟|洪水模拟|二维模拟", "hydrodynamic_2d_sim"),
    (r"什么是|解释|介绍.*概念|原理是|怎么理解", "explain_concept"),
    (r"对比|比选|方案对比|参数对比|方案比较", "auto_tool"),
    (r"糙率|曲线数|CN值|管材|水泵|海绵|暴雨参数", "get_parameter"),
    (r"河网提取|水流累积", "flow_accumulation"),
    (r"流域提取|汇水区|子流域划分", "watershed_delineate"),
    (r"高程|坡度|坡向|曲率|TPI|点位查询|查点|查.*高程|查.*坡度|经度.*纬度.*高程|纬度.*经度.*高程|经纬度.*查询|查.*经纬度", "point_query"),
    (r"地形剖面|纵断面|横断面|剖面线|两点.*高程|断面分析", "terrain_profile"),
    (r"地形分析|DEM分析|DEM坡度|地形统计|地形特征|坡度分布|坡向分布", "dem_analyze"),
    (r"TIN三角网|不规则三角|三角剖分", "tin_generate"),
    (r"四叉树|自适应网格|嵌套剖分", "quadtree_subdivide"),
    (r"暴雨雨型|设计暴雨|暴雨强度公式", "design_storm"),
    (r"SCS.CN|径流系数|产汇流", "runoff_compute"),
    (r"会不会淹|暴雨.*淹|内涝|洪涝|洪水.*淹|3D.*洪水|三维.*洪水|3D淹没|flood_sim_3d", "flood_sim_3d"),
    (r"淹没范围|淹没地图|淹没面积|淹没图|积水", "flood_inundation_map"),
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
    (r"标准检索|查规范|GB\d|SL\d|设计规范|防洪标准|规范条文", "get_standard"),
    (r"率定|校准|参数优化", "calibrate_suggest"),
    (r"DEM渲染|地形渲染", "dem_render"),
    (r"克里金|Kriging|IDW|反距离权重|RBF插值", "scatter_interpolate"),
    (r"文档检索|知识检索|RAG|查文献|技术手册|查手册", "search"),
    (r"天气预报|降雨预报|气象预报", "weather_forecast"),
    (r"卫星影像|遥感|Sentinel|Landsat", "satellite_search"),
    (r"渲染地图|出图|绘制地图", "render_map"),
    (r"3D重建|三维建模|三维重建|reconstruct", "reconstruct_3d"),
    (r"多智能体|多代理|辩论|multi.?agent", "multi_agent_debate"),
    (r"无人机|航线规划|UAV|drone", "drone_mission"),
    (r"降水|降雨|面雨量|precipitation|雨量", "precipitation_grid"),
    (r"建筑|building|房子|楼房", "building_extract"),
    (r"水体变化|水域变化|water.*change", "water_change"),
    (r"水体|水域|水面|water.*monitor", "water_monitor"),
]

# ── Simple Keywords ──
SIMPLE_KEYWORDS = {"你好", "谢谢", "再见", "hello", "hi", "拜拜", "早上好", "晚上好", "谢谢啦", "谢谢你", "哈喽"}

ALL_TOOLS = "hydrodynamic_2d_sim,get_parameter,explain_concept,search,get_standard,dem_analyze,watershed_delineate,flow_accumulation,terrain_profile,point_query,dem_render,tin_generate,quadtree_subdivide,design_storm,runoff_compute,swmm_create_model,swmm_simulate,calibrate_suggest,flood_inundation_map,flood_assessment,drainage_assessment,flood_warning,flood_risk_zones,spatial_query,buffer,overlay,coordinate_transform,geometry_properties,validate_data,render_map,weather_forecast,satellite_search,spatial_knowledge_query,scatter_interpolate,auto_tool,reconstruct_3d,precipitation_grid,building_extract,water_monitor,flood_sim_3d,drone_mission,water_change,multi_agent_debate".split(",")
