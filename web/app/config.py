from __future__ import annotations

import os
import re
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
MODEL_CODE = "glm-4-flash-250414"
MODEL_VISION = "glm-4v-flash"

# ── Cache & Circuit Breaker ──
CACHE_MAX = 200
CACHE_TTL = 300
MAX_CONTEXT_CHARS = 4000
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

# ── Data Paths ──
DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
GEN_TOOL_DIR = DATA_DIR / "generated_tools"
GEN_TOOL_DIR.mkdir(parents=True, exist_ok=True)
RECON_DIR = Path(__file__).parent.parent / "reconstruct"
RECON_OUTPUTS = RECON_DIR / "outputs"

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
- 参数从对话上下文提取实际值
- 工具返回错误时调整参数重试
- 禁止输出Python代码，只能调工具"""

# ── Routing Rules ──
ROUTING_RULES: list[tuple[str, str]] = [
    (r"水动力|淹没模拟|洪水模拟|二维模拟", "hydrodynamic_2d_sim"),
    (r"什么是|解释|介绍.*概念|原理是|怎么理解", "explain_concept"),
    (r"对比|比选|方案对比|参数对比|方案比较", "scenario_compare"),
    (r"全链路|暴雨洪水|完整分析|一条龙|全流程|暴雨.*洪水|洪水.*全链", "storm_flood_pipeline"),
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
    (r"文档检索|知识检索|RAG|查条文|查文献|规范条文|技术手册|查手册", "rag_search"),
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

ALL_TOOLS = "hydrodynamic_2d_sim,get_parameter,explain_concept,search,get_standard,dem_analyze,watershed_delineate,flow_accumulation,terrain_profile,point_query,dem_render,tin_generate,quadtree_subdivide,design_storm,runoff_compute,swmm_create_model,swmm_simulate,calibrate_suggest,flood_inundation_map,flood_assessment,drainage_assessment,flood_warning,flood_risk_zones,spatial_query,buffer,overlay,coordinate_transform,geometry_properties,validate_data,render_map,weather_forecast,satellite_search,spatial_knowledge_query,scatter_interpolate,rag_search,scenario_compare,storm_flood_pipeline,auto_tool,reconstruct_3d,precipitation_grid,building_extract,water_monitor,flood_sim_3d,drone_mission,water_change,multi_agent_debate".split(",")
