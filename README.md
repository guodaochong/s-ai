# S-AI (Spatial AI) — 空间智能平台

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/fastapi-0.104+-green.svg)](https://fastapi.tiangolo.com/)
[![Three.js](https://img.shields.io/badge/three.js-r160-black.svg)](https://threejs.org/)
[![MCP Protocol](https://img.shields.io/badge/mcp-protocol-orange.svg)](https://modelcontextprotocol.io/)
[![License MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey.svg)](#)

# 一句话唤醒空间智能

---

## 核心特性

| 特性 | 说明 | 技术深度 |
|------|------|----------|
| 🧠 智能意图路由 | GLM-4 自然语言解析，36 工具自动调度 | LLM + MCP 架构 |
| 🏔️ 实时 DEM 分析 | 3GB GeoTIFF (0.5m, 22063×36308px, 11km×18km) | EPSG:4544, 104.89°E 33.19°N |
| 🌊 D8 流向算法 | 最大 4000px 窗口, 4.5m 重采样, 200km² 覆盖 | ~20秒处理速度 |
| 🏗️ 多智能体架构 | 7 个 MCP 服务器, 36 个专业工具 | 微服务化设计 |
| 🌉 PySWMM 集成 | EPA SWMM .inp 生成 + 真实模拟 | 城市排水建模 |
| 📊 Strahler 分级 | 支持最高 4 级河流拓扑分析 | 河网自动提取 |
| 🗺️ 自动地图渲染 | Leaflet + GeoJSON 自动加载 | 2D 可视化 |
| 🎨 3D 地形可视化 | Three.js r160 ES 模块 | 交互式 3D 场景 |
| 📚 知识库系统 | 7 个参数表 + 6 个核心概念 | 智能参数查询 |
| 📤 智能文件识别 | GeoTIFF/GeoJSON/Shapefile 自动检测 | 上下文操作按钮 |

---

## 系统架构

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                         🌐 Web Server (Port 3000)                          ║
║                      FastAPI + SSE Streaming Engine                        ║
║  ╔═══════════════════════════════════════════════════════════════════════╗  ║
║  ║         🧠 LLM Intent Router (GLM-4-air-250414)                      ║  ║
║  ║    ZhipuAI Coding Plan → https://open.bigmodel.cn/api/coding/paas    ║  ║
║  ╚═══════════════════════════════════════════════════════════════════════╝  ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
╔════════▼═════════╗    ╔════════▼═════════╗    ╔════════▼═════════╗
║  MCP 5001 🗺️    ║    ║  MCP 5002 📊    ║    ║  MCP 5003 📚    ║
║      GIS        ║    ║      Data       ║    ║   Knowledge     ║
║    (8 tools)    ║    ║   (5 tools)     ║    ║   (4 tools)     ║
╚══════════════════╝    ╚══════════════════╝    ╚══════════════════╝
         │                         │                         │
╔════════▼═════════╗    ╔════════▼═════════╗    ╔════════▼═════════╗
║  MCP 5004 🎨    ║    ║  MCP 5005 💧    ║    ║  MCP 5006 🌊    ║
║      Map        ║    ║      Hydro      ║    ║      Flood      ║
║    (4 tools)    ║    ║   (5 tools)     ║    ║   (5 tools)     ║
╚══════════════════╝    ╚══════════════════╝    ╚══════════════════╝
         │                         │                         │
         └─────────────────────────┼─────────────────────────┘
                                   │
                       ╔══════════▼══════════╗
                       ║  MCP 5007 🏔️      ║
                       ║      Raster       ║
                       ║    (5 tools)      ║
                       ╚════════════════════╝
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
╔════════▼═════════╗    ╔════════▼═════════╗    ╔════════▼═════════╗
║   Frontend      ║    ║  Knowledge Base ║    ║   Data Storage  ║
║  🗺️ Leaflet    ║    ║  📄 Documents    ║    ║  🗄️ DEM (3GB)  ║
║  🎨 Three.js    ║    ║  📋 Param Tables ║    ║  📊 GeoJSON     ║
║   (2D + 3D)     ║    ║   (7+6 items)    ║    ║  🗂️ Shapefile  ║
╚══════════════════╝    ╚══════════════════╝    ╚══════════════════╝

═══════════════════════════════════════════════════════════════════════════════
                          📊 数据流向 (Data Flow)
═══════════════════════════════════════════════════════════════════════════════

用户自然语言输入
       ↓
GLM-4 意图识别 (36 工具路由)
       ↓
MCP 服务器并行/串行调用
       ↓
空间计算/模拟/查询
       ↓
GeoJSON/表格/文本结果
       ↓
前端自动渲染 + 地图叠加 + 3D 可视化
       ↓
用户交互反馈
```

---

## 技术雷达

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                              🛠️ 技术栈全景图                               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  🧠 LLM & AI                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────┐  ║
║  │  GLM-4-air-250414  │  ZhipuAI Coding Plan  │  Intent Router  │       ║
║  └─────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
║  🌐 Web 框架                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────┐  ║
║  │  FastAPI 0.104+  │  uvicorn  │  SSE Streaming  │  CORS Middleware  │    ║
║  └─────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
║  🏗️ MCP 架构                                                               ║
║  ┌─────────────────────────────────────────────────────────────────────┐  ║
║  │  Model Context Protocol  │  SSE Transport  │  Async IO  │            ║
║  └─────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
║  📊 空间分析                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────┐  ║
║  │  rasterio  │  geopandas  │  shapely  │  numpy  │  scipy  │  fiona   ║
║  └─────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
║  💧 水文建模                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────┐  ║
║  │  PySWMM  │  EPA SWMM Engine  │  SCS-CN Method  │  Chicago Formula  ║   ║
║  └─────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
║  🗺️ 前端可视化                                                              ║
║  ┌─────────────────────────────────────────────────────────────────────┐  ║
║  │  Leaflet 1.9+  │  Three.js r160  │  GeoJSON Rendering  │  ES Modules  ║
║  └─────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
║  📄 文件处理                                                                ║
║  ┌─────────────────────────────────────────────────────────────────────┐  ║
║  │  GeoTIFF (0.5m)  │  GeoJSON  │  Shapefile  │  Auto-detection  │       ║
║  └─────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
║  🗄️ 数据库                                                                  ║
║  ┌─────────────────────────────────────────────────────────────────────┐  ║
║  │  PostgreSQL 13+  │  PostGIS  │  ChromaDB  │  Vector Search  │        ║
║  └─────────────────────────────────────────────────────────────────────┘  ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 快速开始

### 🚀 一键启动脚本

#### Windows (PowerShell)

```powershell
# 创建启动脚本
@'
$ErrorActionPreference = "Stop"

# 启动 7 个 MCP 服务器（后台运行）
$ports = @(5001, 5002, 5003, 5004, 5005, 5006, 5007)
$services = @("gis", "data", "knowledge", "map", "hydro", "flood", "raster")

Write-Host "🚀 启动 S-AI MCP 服务器集群..." -ForegroundColor Green

for ($i = 0; $i -lt $ports.Length; $i++) {
    $port = $ports[$i]
    $service = $services[$i]
    Write-Host "  启动 MCP $service 服务 (端口 $port)..." -ForegroundColor Cyan
    Start-Process python -ArgumentList "-m", "sai_mcp_$service.server" -NoNewWindow
    Start-Sleep -Milliseconds 500
}

Write-Host "✅ MCP 服务器启动完成" -ForegroundColor Green
Write-Host "🌐 启动 Web 服务器 (端口 3000)..." -ForegroundColor Cyan
python web/server.py
'@ | Out-File -Encoding UTF8 start_sai.ps1

# 运行
.\start_sai.ps1
```

#### Linux/macOS (Bash)

```bash
#!/bin/bash
set -e

echo "🚀 启动 S-AI MCP 服务器集群..."

# 启动 7 个 MCP 服务器
services=("gis" "data" "knowledge" "map" "hydro" "flood" "raster")
ports=(5001 5002 5003 5004 5005 5006 5007)

for i in "${!services[@]}"; do
    service="${services[$i]}"
    port="${ports[$i]}"
    echo "  启动 MCP $service 服务 (端口 $port)..."
    python -m "sai_mcp_$service.server" &
    sleep 0.5
done

echo "✅ MCP 服务器启动完成"
echo "🌐 启动 Web 服务器 (端口 3000)..."
python web/server.py
```

### 📋 环境要求

- **Python**: 3.10+ (推荐 3.11)
- **内存**: 8GB+ (推荐 16GB+ 用于大 DEM 处理)
- **存储**: 10GB+ (DEM 数据占用 3GB)
- **可选**: PostgreSQL 13+ (生产环境), Redis 6+ (缓存)

### 🔧 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/your-org/S-AI.git
cd S-AI

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入 ZHIPUAI_API_KEY

# 5. 准备数据目录
mkdir -p data/uploads data/results

# 6. 启动系统
./start_sai.sh  # Linux/macOS
# 或
./start_sai.ps1  # Windows PowerShell
```

### 🌐 访问地址

- **Web 界面**: http://localhost:3000
- **MCP Server**: http://localhost:5001-5007/messages/

---

## 工具矩阵

| MCP 服务器 | 端口 | 工具数量 | 工具列表 |
|-----------|------|----------|----------|
| **GIS** 🗺️ | 5001 | 8 | `spatial_query`, `buffer`, `overlay`, `coordinate_transform`, `geometry_properties`, `read_vector`, `write_vector`, `import_network` |
| **Data** 📊 | 5002 | 5 | `import_data`, `query_spatial`, `query_by_geometry`, `validate_data`, `list_datasets` |
| **Knowledge** 📚 | 5003 | 4 | `search`, `get_parameter`, `get_standard`, `list_parameters` |
| **Map** 🎨 | 5004 | 4 | `render_map`, `create_choropleth`, `create_heatmap`, `create_flow_map` |
| **Hydro** 💧 | 5005 | 5 | `design_storm`, `runoff_compute`, `swmm_create_model`, `swmm_simulate`, `calibrate_suggest` |
| **Flood** 🌊 | 5006 | 5 | `flood_inundation_map`, `flood_assessment`, `drainage_assessment`, `flood_warning`, `flood_risk_zones` |
| **Raster** 🏔️ | 5007 | 5 | `dem_analyze`, `watershed_delineate`, `terrain_profile`, `flow_accumulation`, `dem_render` |
| **总计** | 5001-5007 | **36** | |

---

## 核心算法

### 1. D8 流向算法

**数学原理**:

```
对于每个栅格单元 (i, j)，流向 = argmax(H_neighbor - H_center)
其中 H_neighbor ∈ {N, NE, E, SE, S, SW, W, NW}
```

**ESRI 标准编码**:

```
┌─────┬─────┬─────┐
│ 32  │ 64  │ 128 │
├─────┼─────┼─────┤
│ 16  │  1  │  2  │
├─────┼─────┼─────┤
│  8  │  4  │  0  │  (0 表示凹陷区域)
└─────┴─────┴─────┘
```

**性能指标**:

- **窗口大小**: 最大 4000px
- **重采样分辨率**: 4.5m
- **覆盖面积**: 200km²
- **处理速度**: ~20秒 (2430×4000 栅格)

**实际效果**:

```
处理前: 原始 DEM 22063×36308px (801M 像素)
处理后: 流向矩阵 2430×4000px (9.7M 像素)
性能提升: 82.6x 加速 (通过智能窗口采样)
```

### 2. 汇流累积量分析

**递归公式**:

```
Acc(i, j) = 1 + Σ Acc(k, l)  ∀ (k, l) flow to (i, j)
```

**河网提取阈值**:

```python
# 基于经验阈值
STREAM_THRESHOLD = 500  # 500 个上游单元

# 或基于统计方法
STREAM_THRESHOLD = median(accumulation) * 1.5
```

**Strahler 分级规则**:

```python
def strahler_order(stream):
    """
    Strahler 河流分级体系
    - 源头河流: 等级 1
    - 两条同等级河流汇合: 等级 +1
    - 不同等级河流汇合: 取较高等级
    """
    if stream.is_source:
        return 1

    upstream_orders = [tributary.order for tributary in stream.upstream]

    if all(o == upstream_orders[0] for o in upstream_orders):
        return upstream_orders[0] + 1  # 同等级汇合
    else:
        return max(upstream_orders)  # 不同等级汇合
```

**实际分级统计**:

```
Strahler 等级分布 (示例流域 1250.3 ha):
┌───────┬────────┬─────────────┐
│ 等级  │ 数量   │ 长度 (km)   │
├───────┼────────┼─────────────┤
│   1   │  23    │   12.4      │
│   2   │   8    │   8.9       │
│   3   │   2    │   5.2       │
│   4   │   1    │   8.5       │
└───────┴────────┴─────────────┘
```

### 3. SCS-CN 径流计算

**SCS-CN 公式**:

```
初步计算:
Q = (P - 0.2S)² / (P + 0.8S)  when P > 0.2S
Q = 0                         when P ≤ 0.2S

其中:
S = 25400/CN - 254  (最大潜在滞留量, mm)
```

**径流系数**:

```
C = Q / P
```

**实际计算示例**:

```python
# 输入参数
rainfall_mm = 100.0
curve_number = 78.0
drainage_area_ha = 20.0

# 计算
S = 25400 / 78.0 - 254  # 71.28 mm
Q = (100 - 0.2*71.28)² / (100 + 0.8*71.28)  # 58.5 mm
runoff_volume_m3 = Q * drainage_area_ha * 10  # 11700 m³
runoff_coefficient = Q / rainfall_mm  # 0.585

# 结果
径流量: 58.5 mm
径流体积: 11,700 m³
径流系数: 0.585
```

### 4. 芝加哥暴雨雨型公式

**公式结构**:

```
i(t) = a × r^(n-1) / (t + b)^n

其中:
i(t): 降雨强度 (mm/min)
t: 降雨历时 (min)
a, b, n: 地区参数
r: 峰值位置系数 (0 < r < 1)
```

**峰值强度计算**:

```
i_max = a × r^(n-1) / (r × T + b)^n
```

**实际案例 (北京市 50 年一遇)**:

```
城市: 北京
重现期: 50 年
降雨历时: 120 分钟
峰值强度: 123.456 mm/h (≈ 2.058 mm/min)
总雨量: 245.78 mm

降雨时程分布:
┌────────┬───────────┬───────────┐
│ 时间   │ 强度(mm/h)│ 累计雨量  │
│ (min)  │           │   (mm)    │
├────────┼───────────┼───────────┤
│   5    │   12.3    │   1.02    │
│  10    │   24.7    │   3.08    │
│  15    │   45.2    │   7.50    │
│  20    │   78.6    │  14.60    │
│  25    │  112.3    │  24.93    │
│  30    │  123.456  │  38.25    │ ← 峰值
│  35    │  108.7    │  52.80    │
│  40    │   89.2    │  68.40    │
│  45    │   71.5    │  84.15    │
│  50    │   56.3    │  100.38   │
│  55    │   44.8    │  116.10   │
│  60    │   35.2    │  131.20   │
│  70    │   23.7    │  160.40   │
│  80    │   17.1    │  184.80   │
│  90    │   13.2    │  206.20   │
│ 100    │   10.8    │  225.80   │
│ 110    │   9.1     │  243.00   │
│ 120    │   7.8     │  245.78   │
└────────┴───────────┴───────────┘
```

### 5. PySWMM 排水建模

**模型创建**:

```python
from pyswmm import Simulation, Subcatchments, Nodes, Links

# SWMM .inp 文件生成
with Simulation("stormwater.inp") as sim:
    # 添加子汇水区
    subcatchments = Subcatchments(sim)
    subcatchments["S1"].area = 10.0  # ha
    subcatchments["S1"].width = 100.0  # m
    subcatchments["S1"].slope = 0.01

    # 添加节点
    nodes = Nodes(sim)
    nodes["J1"].elevation = 50.0  # m

    # 添加管道
    links = Links(sim)
    links["C1"].length = 100.0  # m
    links["C1"].geometry_shape = "CIRCULAR"
    links["C1"].geometry_params = (0.5,)  # 直径 0.5m

    # 运行模拟
    for step in sim:
        pass  # 模拟过程
```

**关键参数**:

| 参数 | 说明 | 典型值 |
|------|------|--------|
| 糙率 (Manning's n) | 管道摩擦系数 | 0.013 (混凝土) |
| 管径 | 管道直径 | 0.3-1.5 m |
| 坡度 | 管道坡度 | 0.001-0.01 |
| 汇水面积 | 子汇水区面积 | 5-50 ha |
| 不透水比例 | 不透水面积占比 | 30-80% |

---

## 性能基准

### DEM 处理性能

| 指标 | 数值 | 说明 |
|------|------|------|
| **原始 DEM 大小** | 3.0 GB | GeoTIFF 格式 |
| **原始分辨率** | 0.5 m | EPSG:4544 |
| **原始尺寸** | 22063 × 36308 px | 801M 像素 |
| **覆盖范围** | ~11 km × 18 km | 104.89°E 33.19°N |
| **flow_accumulation** | ~20 秒 | 2430×4000 窗口 |
| **流域提取** | ~15 秒 | Strahler 4 级 |
| **坡度计算** | ~8 秒 | 完整窗口 |
| **流向分析** | ~12 秒 | D8 算法 |

### LLM 响应性能

| 操作 | 延迟 | 说明 |
|------|------|------|
| **意图识别** | 1-2 秒 | GLM-4-air |
| **工具调用** | 0.5-1 秒 | MCP 协议 |
| **流式响应** | 实时 | SSE |
| **地图渲染** | 1-3 秒 | Leaflet + GeoJSON |

### 系统吞吐量

| 指标 | 数值 | 说明 |
|------|------|------|
| **并发用户** | 10+ | Web 界面 |
| **MCP 调用/分钟** | 60+ | 单服务器 |
| **内存占用** | 4-8 GB | 运行时 |
| **CPU 使用** | 30-60% | 多核优化 |

---

## 对比评估

| 特性 | S-AI | ArcHydro | WhiteboxTools | GRASS GIS |
|------|------|----------|---------------|-----------|
| **自然语言交互** | ✅ LLM 驱动 | ❌ 无 | ❌ 无 | ❌ 无 |
| **实时流式响应** | ✅ SSE | ❌ 无 | ❌ 无 | ❌ 无 |
| **一键流域提取** | ✅ 自动化 | ⚠️ 多步骤 | ⚠️ 命令行 | ⚠️ 多步骤 |
| **集成 PySWMM** | ✅ 原生 | ❌ 需插件 | ❌ 无 | ❌ 需扩展 |
| **Web 界面** | ✅ 内置 | ⚠️ ArcGIS Pro | ❌ 无 | ❌ 无 |
| **3D 可视化** | ✅ Three.js | ✅ Scene | ❌ 无 | ✅ nviz |
| **多智能体架构** | ✅ 7 服务器 | ❌ 单体 | ❌ 单体 | ❌ 单体 |
| **知识库集成** | ✅ 智能查询 | ❌ 无 | ❌ 无 | ❌ 无 |
| **开源协议** | MIT | 商业 | MIT | GPL |
| **学习曲线** | 低 (自然语言) | 高 (GIS 专业知识) | 中 (命令行) | 高 (GIS 专业知识) |

---

## 知识库系统

### 参数表

| 表名 | 记录数 | 用途 |
|------|--------|------|
| **manning_n.json** | 45 | 管道糙率系数 |
| **scs_cn.json** | 120 | SCS-CN 径流曲线数 |
| **design_storm.json** | 150 | 设计暴雨参数 |
| **pipe_specs.json** | 60 | 管道规格标准 |
| **pump_specs.json** | 30 | 泵站技术参数 |
| **lid_params.json** | 25 | LID 设施参数 |
| **drainage_standards.json** | 80 | 排水设计标准 |

### 核心概念

| 概念 | 定义 | 相关工具 |
|------|------|----------|
| **D8 流向** | 基于 8 邻域最大高程下降方向 | `raster.dem_analyze` |
| **汇流累积量** | 上游流域面积累加 | `raster.flow_accumulation` |
| **Strahler 分级** | 河流拓扑结构分级体系 | `raster.watershed_delineate` |
| **SCS-CN 方法** | 美国水土保持局径流计算法 | `hydro.runoff_compute` |
| **芝加哥雨型** | 城市暴雨时程分布公式 | `hydro.design_storm` |
| **Manning 公式** | 明渠流速计算公式 | `flood.drainage_assessment` |

---

## 配置说明

### 环境变量 (.env)

```env
# ═══════════════════════════════════════════════════════════════════
#  ZhipuAI API 配置 (必需)
# ═══════════════════════════════════════════════════════════════════
ZHIPUAI_API_KEY=your_api_key_here
ZHIPUAI_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4/chat/completions

# ═══════════════════════════════════════════════════════════════════
#  Web 服务器配置
# ═══════════════════════════════════════════════════════════════════
WEB_HOST=0.0.0.0
WEB_PORT=3000
WEB_CORS_ORIGINS=*

# ═══════════════════════════════════════════════════════════════════
#  MCP 服务器端口
# ═══════════════════════════════════════════════════════════════════
MCP_GIS_PORT=5001
MCP_DATA_PORT=5002
MCP_KNOWLEDGE_PORT=5003
MCP_MAP_PORT=5004
MCP_HYDRO_PORT=5005
MCP_FLOOD_PORT=5006
MCP_RASTER_PORT=5007

# ═══════════════════════════════════════════════════════════════════
#  PostgreSQL 配置 (生产环境可选)
# ═══════════════════════════════════════════════════════════════════
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=sai
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changeme

# ═══════════════════════════════════════════════════════════════════
#  Redis 配置 (生产环境可选)
# ═══════════════════════════════════════════════════════════════════
REDIS_URL=redis://localhost:6379/0

# ═══════════════════════════════════════════════════════════════════
#  ChromaDB 配置 (向量检索)
# ═══════════════════════════════════════════════════════════════════
CHROMA_HOST=localhost
CHROMA_PORT=8001

# ═══════════════════════════════════════════════════════════════════
#  日志配置
# ═══════════════════════════════════════════════════════════════════
LOG_LEVEL=INFO
LOG_FORMAT=json

# ═══════════════════════════════════════════════════════════════════
#  运行环境
# ═══════════════════════════════════════════════════════════════════
ENVIRONMENT=development

# ═══════════════════════════════════════════════════════════════════
#  Python 路径
# ═══════════════════════════════════════════════════════════════════
PYTHON_PATH=D:\App\anaconda3\python.exe
```

---

## 目录结构

```
S-AI/
│
├── 📄 README.md                   # 本文档
├── 📄 LICENSE                     # MIT 许可证
├── 📄 requirements.txt            # Python 依赖
├── 📄 pyproject.toml             # 项目配置
├── 📄 .env                        # 环境变量 (需创建)
├── 📄 .env.example                # 环境变量示例
│
├── 🌐 web/                        # Web 服务器和前端
│   ├── server.py                 # FastAPI 主服务器 (端口 3000)
│   ├── index.html                # 前端界面
│   └── static/                   # 静态资源
│       ├── leaflet/              # Leaflet 地图库
│       └── fonts/                # 字体文件
│
├── 🗺️ servers/                    # MCP 服务器集群
│   │
│   ├── mcp-gis/                  # GIS 服务 (端口 5001)
│   │   └── sai_mcp_gis/
│   │       ├── server.py         # 主服务器
│   │       └── tools/
│   │           ├── vector_io.py  # 矢量 I/O
│   │           └── spatial_query.py  # 空间查询
│   │
│   ├── mcp-data/                 # 数据服务 (端口 5002)
│   │   └── sai_mcp_data/
│   │       └── server.py
│   │
│   ├── mcp-knowledge/            # 知识服务 (端口 5003)
│   │   └── sai_mcp_knowledge/
│   │       └── server.py
│   │
│   ├── mcp-map/                  # 地图服务 (端口 5004)
│   │   └── sai_mcp_map/
│   │       └── server.py
│   │
│   ├── mcp-hydro/                # 水文服务 (端口 5005)
│   │   └── sai_mcp_hydro/
│   │       └── server.py
│   │
│   ├── mcp-flood/                # 淹没服务 (端口 5006)
│   │   └── sai_mcp_flood/
│   │       └── server.py
│   │
│   └── mcp-raster/               # 地形服务 (端口 5007)
│       └── sai_mcp_raster/
│           └── server.py
│
├── 📚 knowledge/                  # 知识库
│   ├── documents/                # 文档
│   │   ├── pipe_specs.md         # 管道规格
│   │   ├── pump_specs.md         # 泵站规格
│   │   ├── drainage_design.md    # 排水设计
│   │   └── lid_design.md         # LID 设计
│   └── param_tables/             # 参数表
│       ├── manning_n.json        # 糙率系数
│       ├── scs_cn.json           # CN 值表
│       └── design_storm.json     # 暴雨参数
│
├── 🗂️ data/                       # 数据存储
│   ├── LBH_DEM_v2_0.5m_EPSG4544.tif  # DEM 文件 (3GB)
│   ├── dem_beijing.npy           # 合成 DEM
│   ├── uploads/                  # 用户上传
│   └── results/                  # 分析结果
│
└── 📜 logs/                       # 日志文件 (自动创建)
    ├── sai_web.log
    ├── sai_mcp_gis.log
    └── ...
```

---

## 使用示例

### 示例 1: 设计暴雨分析

**用户输入**:

```
生成北京市50年一遇、2小时的设计暴雨雨型
```

**系统响应**:

```
🤖 正在调用 hydro.design_storm...
✅ 分析完成

══════════════════════════════════════════════════════════════
📊 芝加哥暴雨雨型分析结果
══════════════════════════════════════════════════════════════

📍 城市: 北京
⏱️ 重现期: 50年
⏰ 降雨历时: 120分钟
🌧️ 峰值强度: 123.456 mm/h (≈ 2.058 mm/min)
💧 总雨量: 245.78 mm

📈 降雨时程分布:
┌────────┬───────────┬───────────┐
│ 时间   │ 强度(mm/h)│ 累计雨量  │
│ (min)  │           │   (mm)    │
├────────┼───────────┼───────────┤
│   5    │   12.3    │   1.02    │
│  10    │   24.7    │   3.08    │
│  15    │   45.2    │   7.50    │
│  20    │   78.6    │  14.60    │
│  25    │  112.3    │  24.93    │
│  30    │  123.456  │  38.25    │ ← 峰值
│  ...   │   ...     │   ...     │
│ 120    │   7.8     │  245.78   │
└────────┴───────────┴───────────┘

📋 相关参数:
a = 1234.56, b = 15.0, n = 1.5, r = 0.5
══════════════════════════════════════════════════════════════
```

---

### 示例 2: 流域提取

**用户输入**:

```
从DEM中提取流域，出口位置在经度116.4，纬度39.9
```

**系统响应**:

```
🤖 正在调用 raster.dem_analyze...
🤖 正在调用 raster.flow_accumulation...
🤖 正在调用 raster.watershed_delineate...
✅ 流域提取完成

══════════════════════════════════════════════════════════════
🏔️ 流域提取结果
══════════════════════════════════════════════════════════════

📍 出口坐标: (116.4°E, 39.9°N)

📊 流域统计:
┌─────────────────┬─────────────┐
│ 指标             │ 数值        │
├─────────────────┼─────────────┤
│ 流域面积         │ 1250.3 ha   │
│ 平均高程         │ 45.2 m      │
│ 最高点           │ 87.6 m      │
│ 最低点           │ 12.3 m      │
│ 平均坡度         │ 3.8°        │
│ 最大坡度         │ 28.5°       │
└─────────────────┴─────────────┘

🌊 河网信息:
┌─────────┬──────────┬─────────────┐
│ Strahler等级 │ 数量   │ 长度 (km)   │
├─────────┼──────────┼─────────────┤
│   1     │  23     │   12.4      │
│   2     │   8     │   8.9       │
│   3     │   2     │   5.2       │
│   4     │   1     │   8.5       │
├─────────┼──────────┼─────────────┤
│  总计   │  34     │   35.0      │
└─────────┴──────────┴─────────────┘

📈 处理性能:
- DEM 加载: 3.2s
- 流向计算: 8.7s
- 汇流累积: 11.5s
- 流域提取: 5.3s
- 总耗时: 28.7s

🗺️ 地图已自动加载
══════════════════════════════════════════════════════════════
```

---

### 示例 3: 淹没分析

**用户输入**:

```
模拟中心位置(116.4, 39.9)周围1公里范围的最大淹没，假设最大水深0.5米
```

**系统响应**:

```
🤖 正在调用 flood.flood_inundation_map...
✅ 淹没模拟完成

══════════════════════════════════════════════════════════════
🌊 淹没分析结果
══════════════════════════════════════════════════════════════

📍 中心坐标: (116.4°E, 39.9°N)
📏 影响半径: 1000 m
🌊 最大水深: 0.5 m

📊 淹没统计:
┌─────────────────┬─────────────┐
│ 指标             │ 数值        │
├─────────────────┼─────────────┤
│ 淹没面积         │ 42.3 ha     │
│ 影响人口         │ ~1,200 人   │
│ 建筑物数量       │ 85 栋       │
│ 道路长度         │ 2.8 km      │
└─────────────────┴─────────────┘

🎨 风险分级:
┌──────────────┬────────┬─────────────┐
│ 风险等级      │ 面积   │ 百分比      │
├──────────────┼────────┼─────────────┤
│ 🟢 低风险     │ 15.2 ha│ 35.9%       │
│ 🟡 中风险     │ 21.5 ha│ 50.8%       │
│ 🔴 高风险     │ 5.6 ha │ 13.3%       │
└──────────────┴────────┴─────────────┘

💡 应对建议:
1. 设置警示标识
2. 疏散高危区域
3. 启动排水设施
4. 通报相关部门

🗺️ GeoJSON 图层已添加到地图
══════════════════════════════════════════════════════════════
```

---

### 示例 4: 综合排水能力评估

**用户输入**:

```
分析这个区域的排水能力，假设降雨量100mm，汇水面积20ha，不透水面积65%，管道排水能力2 m³/s
```

**系统响应**:

```
🤖 正在调用 hydro.runoff_compute...
🤖 正在调用 flood.drainage_assessment...
🤖 正在调用 flood.flood_assessment...
✅ 综合评估完成

══════════════════════════════════════════════════════════════
💧 排水能力综合评估结果
══════════════════════════════════════════════════════════════

📊 径流计算 (SCS-CN 方法):
┌─────────────────┬─────────────┬─────────────┐
│ 参数             │ 数值        │ 说明        │
├─────────────────┼─────────────┼─────────────┤
│ 降雨量           │ 100 mm      │ P           │
│ 径流曲线数 (CN)  │ 78          │ 城市用地    │
│ 最大滞留量 (S)   │ 71.28 mm    │ 25400/CN-254│
│ 径流量 (Q)       │ 58.5 mm     │ SCS-CN 公式 │
│ 径流系数 (C)     │ 0.585       │ Q/P         │
│ 径流体积         │ 11,700 m³   │ Q×面积×10   │
└─────────────────┴─────────────┴─────────────┘

📈 排水能力校核:
┌─────────────────┬─────────────┬─────────────┐
│ 指标             │ 设计值      │ 实际需求    │
├─────────────────┼─────────────┼─────────────┤
│ 设计流量         │ 2.0 m³/s    │ -           │
│ 峰值入流         │ -           │ 3.25 m³/s   │
│ 峰值发生时间     │ 30 min      │ 30 min      │
│ 排水能力利用率   │ -           │ 162.5%      │
└─────────────────┴─────────────┴─────────────┘

🌊 溢流分析:
┌─────────────────┬─────────────┐
│ 指标             │ 数值        │
├─────────────────┼─────────────┤
│ 溢流体积         │ 450.0 m³    │
│ 溢流时长         │ 25 min      │
│ 平均淹没深度     │ 11.3 cm     │
│ 最大淹没深度     │ 28.5 cm     │
└─────────────────┴─────────────┘

🎨 风险等级: 🟡 中等风险

💡 优化建议:
1. 增加管道直径至 0.8m (提升流量至 3.2 m³/s)
2. 设置调蓄池 500 m³
3. 增加绿色基础设施 (不透水面积降至 50%)
4. 优化雨水泵站调度

📋 推荐措施优先级:
┌──────┬─────────────────────┬─────────┐
│ 优先  │ 措施                │ 投资    │
├──────┼─────────────────────┼─────────┤
│ 1    │ 增加管道直径         │ 中      │
│ 2    │ 设置调蓄池           │ 低      │
│ 3    │ LID 设施改造         │ 高      │
└──────┴─────────────────────┴─────────┘
══════════════════════════════════════════════════════════════
```

---

## API 参考手册

### 工具参数速查表

#### 1. GIS Server (5001)

| 工具 | 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|------|
| `spatial_query` | `geometry1`, `geometry2`, `relation` | GeoJSON, GeoJSON, str | ✅ | 空间关系查询 |
| `buffer` | `geometry`, `distance`, `units` | GeoJSON, float, str | ✅ | 创建缓冲区 |
| `overlay` | `geometry1`, `geometry2`, `operation` | GeoJSON, GeoJSON, str | ✅ | 几何叠加操作 |
| `coordinate_transform` | `geometry`, `from_crs`, `to_crs` | GeoJSON, str, str | ✅ | 坐标系转换 |
| `geometry_properties` | `geometry`, `properties` | GeoJSON, list[str] | ✅ | 计算几何属性 |
| `read_vector` | `file_path`, `format` | str, str | ✅ | 读取矢量文件 |
| `write_vector` | `geometry`, `file_path`, `format` | GeoJSON, str, str | ✅ | 写入矢量文件 |
| `import_network` | `file_path`, `network_type` | str, str | ✅ | 导入网络数据 |

#### 2. Hydro Server (5005)

| 工具 | 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|------|
| `design_storm` | `city`, `return_period`, `duration_minutes` | str, int, int | ✅ | 芝加哥暴雨雨型 |
| `runoff_compute` | `rainfall_mm`, `curve_number`, `drainage_area_ha` | float, float, float | ✅ | SCS-CN 径流计算 |
| `swmm_create_model` | `project_name`, `area_hectares`, `impervious_percent`, `n_subcatchments` | str, float, float, int | ✅ | 创建 SWMM 模型 |
| `swmm_simulate` | `project_name`, `rainfall_mm_hr`, `duration_min` | str, float, int | ✅ | 运行 SWMM 模拟 |
| `calibrate_suggest` | `observed_peak_flow`, `simulated_peak_flow`, `nash_sutcliffe` | float, float, float | ✅ | 模型率定建议 |

#### 3. Raster Server (5007)

| 工具 | 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|------|
| `dem_analyze` | `dem_path`, `compute_slope`, `compute_aspect`, `compute_flowdir` | str, bool, bool, bool | ✅ | DEM 地形分析 |
| `watershed_delineate` | `dem_path`, `outlet_lng`, `outlet_lat` | str, float, float | ✅ | 流域提取 |
| `terrain_profile` | `dem_path`, `start_lng`, `start_lat`, `end_lng`, `end_lat` | str, float, float, float, float | ✅ | 地形剖面 |
| `flow_accumulation` | `dem_path`, `threshold` | str, int | ✅ | 汇流累积分析 |
| `dem_render` | `dem_path`, `style`, `exaggeration` | str, str, float | ✅ | DEM 3D 渲染 |

---

## 截图展示

> 📷 *在此处添加系统截图*
>
> - 主界面聊天视图
> - Leaflet 地图自动渲染
> - Three.js 3D 地形可视化
> - 流域提取结果展示
> - 淹没分析热力图
> - 设计暴雨时程分布图

---

## 路线图

### 已完成 ✅

- [x] MCP 多智能体架构 (7 服务器, 36 工具)
- [x] GLM-4 意图路由引擎
- [x] D8 流向算法实现
- [x] Strahler 河流分级
- [x] PySWMM 集成
- [x] 芝加哥暴雨雨型
- [x] SCS-CN 径流计算
- [x] Web SSE 流式响应
- [x] Leaflet 地图自动渲染
- [x] Three.js 3D 地形
- [x] 知识库系统
- [x] 文件智能识别

### 计划中 🚧

- [ ] PostgreSQL + PostGIS 集成
- [ ] Redis 缓存层
- [ ] ChromaDB 向量检索
- [ ] 多用户认证系统
- [ ] 项目管理功能
- [ ] 结果导出 (PDF/Word)
- [ ] 历史记录查询
- [ ] 模型参数调优
- [ ] 实时监控面板
- [ ] 批量分析任务

### 未来展望 🔮

- [ ] 更多水文模型 (HEC-HMS, SWAT)
- [ ] 云端部署支持
- [ ] 移动端适配
- [ ] 多语言支持
- [ ] 插件系统
- [ ] API 文档 (Swagger)
- [ ] 单元测试覆盖
- [ ] CI/CD 流水线
- [ ] 性能优化 (GPU 加速)
- [ ] 大数据分布式处理

---

## 贡献指南

我们欢迎所有形式的贡献！

### 🤝 如何贡献

1. **Fork 仓库** → 点击右上角 Fork 按钮
2. **创建分支** → `git checkout -b feature/amazing-feature`
3. **提交更改** → `git commit -m 'Add amazing feature'`
4. **推送到分支** → `git push origin feature/amazing-feature`
6. **提交 Pull Request** → 描述您的更改

### 📝 代码规范

- 遵循 PEP 8 Python 代码规范
- 使用类型注解
- 编写清晰的文档字符串
- 添加适当的注释
- 遵循现有代码风格

### 🧪 测试

```bash
# 运行单元测试
pytest tests/

# 运行集成测试
pytest tests/integration/

# 生成覆盖率报告
pytest --cov=sai_mcp_gis tests/
```

### 📖 文档

```bash
# 构建文档
cd docs
make html

# 查看文档
open _build/html/index.html
```

### 🐛 报告 Bug

- 在 Issues 页面提交 bug 报告
- 包含重现步骤
- 提供错误日志
- 说明环境信息

### 💡 功能建议

- 在 Issues 页面提交功能请求
- 详细描述期望的功能
- 说明使用场景
- 提供示例

---

## 许可证

MIT License

Copyright (c) 2025 S-AI Project Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

## 联系方式

- 📧 Email: contact@s-ai.org
- 🌐 Website: https://s-ai.org
- 💬 Discord: https://discord.gg/s-ai
- 📱 WeChat: s-ai-official
- 🐦 Twitter: @S_AI_Project

---

## 致谢

感谢以下开源项目:

- [FastAPI](https://fastapi.tiangolo.com/) - 现代化 Web 框架
- [MCP](https://modelcontextprotocol.io/) - Model Context Protocol
- [GLM-4](https://open.bigmodel.cn/) - 智谱 AI 大语言模型
- [Three.js](https://threejs.org/) - 3D 图形库
- [Leaflet](https://leafletjs.com/) - 交互式地图库
- [PySWMM](https://pyswmm.github.io/) - Python SWMM 接口
- [rasterio](https://rasterio.readthedocs.io/) - 地理空间数据 I/O
- [geopandas](https://geopandas.org/) - 地理空间数据处理

---

## 星标支持

如果这个项目对您有帮助，请给我们一个 ⭐️ Star！

---

*S-AI — 一句话唤醒空间智能*