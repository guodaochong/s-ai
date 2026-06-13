<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/Vue_3.5-4FC08D?style=for-the-badge&logo=vue.js&logoColor=white">
  <img src="https://img.shields.io/badge/Three.js-r160-black?style=for-the-badge&logo=three.js&logoColor=white">
  <img src="https://img.shields.io/badge/FastAPI-0.104+-009688?style=for-the-badge&logo=fastapi&logoColor=white">
  <img src="https://img.shields.io/badge/GLM-5.1-6366F1?style=for-the-badge">
  <img src="https://img.shields.io/badge/MCP-Protocol-F97316?style=for-the-badge">
  <img src="https://img.shields.io/badge/license-MIT-blue?style=for-the-badge">
</p>

<h1 align="center">
  S-AI · 水利空间智能体平台
</h1>

<p align="center">
  <em>以自然语言为接口，以空间计算为引擎，以认知智能为灵魂——</em><br>
  <strong>S-AI</strong> 是一座架设于人类语言与地球表面之间的认知桥梁。<br>
  用一句话唤醒沉睡在地形数据中的智慧，让每一滴雨水的轨迹都清晰可辨。
</p>

---

## ◆ 理念 · 为什么需要 S-AI

传统空间信息系统的门槛高悬：用户需要理解坐标系、掌握工具参数、熟记操作流程。而真正的专家思维——"先看地形，再算汇流，然后评估淹没风险"——这种链式推理能力，被锁在 GIS 工程师的大脑里。

**S-AI 打破了这个壁垒。**

我们将 **GLM 大语言模型的推理能力**、**MCP 微服务协议的工具编排能力**、**Leaflet + Three.js 的空间可视化能力**编织成一个有机整体。这不是一个套了地图壳的聊天机器人——这是一个**真正理解"空间"的人工智能体**：它能从一句自然语言中推断出你需要什么工具、什么参数、什么顺序，并自主完成从 DEM 采样到三维渲染的全链路计算。

```
"查询纬度33.197经度104.893的高程和坡度"
  → GLM ReAct 推理 → Raster 服务 DEM 采样 → 结果渲染到对话 + 地图标注

"帮我做一个完整的流域分析"
  → auto-pipeline → DEM分析 → 河网提取 → 流域边界 → 汇流累积 → 地图叠加

"这个区域如果发生百年一遇暴雨，哪里会被淹？"
  → 设计暴雨生成 → SCS-CN径流 → 洪水淹没 → 风险分区 → 3D水动力模拟
```

---

## ◆ 系统架构 · 全景

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           🖥️ Vue 3 前端 (Port 5173)                             │
│                                                                                 │
│  ┌──────────┐  ┌──────────────────────────────┐  ┌───────────────────────────┐ │
│  │  SideBar  │  │       MapPanel               │  │     ChatPanel             │ │
│  │           │  │                               │  │                           │ │
│  │ · Agent   │  │  Leaflet (CartoDB Dark)       │  │  SSE 实时对话流            │ │
│  │   面板    │  │  Three.js 3D 地形渲染         │  │  思考框 (Spinner+进度)     │ │
│  │ · 对话    │  │  水动力 ShaderMaterial 模拟   │  │  工具状态 (⏳→✅ 实时)     │ │
│  │   历史    │  │  图层管理 (GeoJSON 叠加)      │  │  18+ 工具渲染策略          │ │
│  │ · 系统    │  │  水位控制 + 时间线播放器       │  │  导出 (GeoJSON/报告)      │ │
│  │   信息    │  │  示例图层 + 坐标拾取          │  │  Auto-pipeline 链式推理   │ │
│  └──────────┘  └──────────────────────────────┘  └───────────────────────────┘ │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                    WorkflowEditor (DAG 智能体编排)                        │   │
│  │   拖拽画布 · SVG Bezier 连线 · 节点状态机 · 模板系统 · 拓扑执行          │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  Pinia Stores: chat.ts · map.ts · three.ts                                     │
│  Composables: useSSE.ts · useToolRenderer.ts · useServices.ts                  │
│  Build: Vite 8 (rolldown) · TypeScript · TailwindCSS v3                        │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │ HTTP/SSE (Vite Proxy :5173 → :3000)
┌────────────────────────────────────▼────────────────────────────────────────────┐
│                    ⚡ FastAPI Orchestration Layer (Port 3000)                     │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                       🧠 GLM-5.1 推理引擎                                │   │
│  │                                                                          │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │   │
│  │  │  三层路由     │  │  ReAct 推理   │  │  辩论验证     │  │  思维树      │ │   │
│  │  │  L1→L2→L3   │  │  8步链式调用  │  │  3角色共识    │  │  ToT 广度搜索│ │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │   │
│  │                                                                          │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │   │
│  │  │  自动工具生成 │  │  自修复引擎   │  │  常识注入     │  │  物理校验    │ │   │
│  │  │  LLM→Python  │  │  失败→修复    │  │  领域知识增强  │  │  水力学约束  │ │   │
│  │  └─────────────┘  └──────────────┘  └──────────────┘  └──────────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                       🛡️ 可靠性基础设施                                   │   │
│  │                                                                          │   │
│  │  ┌──────────┐  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌─────────┐ │   │
│  │  │  熔断器   │  │  结果缓存  │  │  可观测追踪 │  │  自进化   │  │  记忆库  │ │   │
│  │  │  3次熔断  │  │  LRU 200  │  │  Trace Span│  │  路由学习 │  │  SQLite │ │   │
│  │  │  120s冷却 │  │  5min TTL │  │  全链路记录 │  │  精度统计 │  │  Episode│ │   │
│  │  └──────────┘  └───────────┘  └───────────┘  └───────────┘  └─────────┘ │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │                       🔮 数字孪生桥梁                                     │   │
│  │                                                                          │   │
│  │  ┌───────────────┐  ┌────────────────┐  ┌────────────────────────────┐  │   │
│  │  │ DEM 数据源     │  │  气象预报 API   │  │  可扩展数据源注册表        │  │   │
│  │  │ 0.5m EPSG:4544│  │  Open-Meteo     │  │  file · api · stream      │  │   │
│  │  │ 22K×36K px    │  │  3天预报缓存    │  │  健康检查 + 自动发现       │  │   │
│  │  └───────────────┘  └────────────────┘  └────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │ MCP Protocol (HTTP/JSON)
     ┌───────────┬───────────┬───────┴───────┬───────────┬───────────┬───────────┐
     │           │           │               │           │           │           │
┌────▼────┐ ┌────▼────┐ ┌────▼────┐  ┌──────▼────┐ ┌────▼────┐ ┌────▼────┐ ┌────▼────┐
│ GIS     │ │ Data    │ │Knowl-   │  │ Map       │ │ Hydro   │ │ Flood   │ │ Raster  │
│ :5001   │ │ :5002   │ │ edge    │  │ :5004     │ │ :5005   │ │ :5006   │ │ :5007   │
│         │ │         │ │ :5003   │  │           │ │         │ │         │ │         │
│ 8 tools │ │5 tools  │ │4 tools  │  │ 4 tools   │ │5 tools  │ │5 tools  │ │5 tools  │
│         │ │         │ │         │  │           │ │         │ │         │ │         │
│ spatial │ │read_    │ │search   │  │render_map │ │design_  │ │flood_   │ │dem_     │
│ _query  │ │vector   │ │get_     │  │weather_   │ │storm    │ │inunda-  │ │analyze  │
│ buffer  │ │write_   │ │param    │  │forecast   │ │scs_cn   │ │tion_map │ │flow_    │
│ overlay │ │vector   │ │explain_ │  │satellite_ │ │swmm_    │ │flood_   │ │accumu-  │
│ coord_  │ │validate │ │concept  │  │search     │ │simulate │ │assess-  │ │lation   │
│ trans-  │ │         │ │get_     │  │spatial_   │ │cali-    │ │ment     │ │water-   │
│ form    │ │         │ │standard │  │knowledge  │ │brate    │ │drainage │ │shed_    │
│ geometry│ │         │ │         │  │           │ │         │ │flood_   │ │delineate│
│ _props  │ │         │ │         │  │           │ │         │ │warning  │ │terrain_ │
│ import_ │ │         │ │         │  │           │ │         │ │flood_   │ │profile  │
│ network │ │         │ │         │  │           │ │hydro-   │ │risk_zone│ │scatter_ │
│         │ │         │ │         │  │           │ │dynamic  │ │         │ │interp   │
│         │ │         │ │         │  │           │ │_2d_sim  │ │         │ │tin_gen  │
│         │ │         │ │         │  │           │ │         │ │         │ │quadtree │
└─────────┘ └─────────┘ └─────────┘  └───────────┘ └─────────┘ └─────────┘ └─────────┘
```

---

## ◆ 核心引擎 · 深度解析

### 1. 三层智能路由 (L1 → L2 → L3)

```
用户输入: "这个区域百年一遇暴雨会淹到哪里？"
     │
     ▼
┌─ L1: 关键词快速匹配 ──────────────────────────────────────────────┐
│  127+ 预置规则，覆盖高频水利查询                                     │
│  "暴雨" → hydro层 | "淹没" → flood层 | "高程" → raster层           │
│  命中率 ~70%，延迟 <1ms                                             │
└────────────────────────────┬────────────────────────────────────────┘
                             │ 未命中
                             ▼
┌─ L2: LLM 意图分类 ──────────────────────────────────────────────┐
│  GLM-4-flash 推断意图 → 映射到 7 个服务域                           │
│  延迟 ~500ms，准确率 ~90%                                          │
└────────────────────────────┬────────────────────────────────────────┘
                             │ 置信度不足
                             ▼
┌─ L3: auto_tool 兜底 ────────────────────────────────────────────┐
│  LLM 直接生成 Python 工具代码 → 沙箱执行 → 结果渲染                  │
│  兜底一切无法归类的需求，零工具盲区                                   │
└──────────────────────────────────────────────────────────────────┘
```

### 2. ReAct 推理引擎

每个用户请求触发一个 ReAct (Reasoning + Acting) 循环，最多 8 步链式推理：

```
Step 1/8: 💭 分析用户请求...
          🎯 决定调用: dem_analyze({"lat":33.197,"lng":104.893})
          ✅ 结果: elevation=2847m, slope=32.5°

Step 2/8: 💭 结果分析...
          🎯 决定调用: flow_accumulation({"lat":33.197,"lng":104.893})
          ✅ 结果: flow_acc=1247, 流向=SE

Step 3/8: 💭 综合分析完成
          ✅ 推理完成，共3步，调用2个工具
```

每步可选 36 个工具中的任意组合，自动串联上下文（前一步的输出可作为下一步的输入）。

### 3. 辩论验证 (Debate Validation)

对于关键工具（洪水淹没、风险评估、SWMM 模拟、2D 水动力），结果必须通过**三角色辩论共识**：

| 角色 | 职责 | 评估维度 |
|------|------|---------|
| 🔬 物理验证专家 | 水力学规律一致性 | 流速范围、水深合理性 |
| 📊 数据合理性专家 | 数值范围校验 | 统计分布、异常值检测 |
| ✅ 任务完整性专家 | 需求覆盖度 | 是否完整回答用户问题 |

三个角色独立打分 (1-10)，至少 2 个通过 + 平均分 ≥ 6 → 共识通过。否则返回警告。

### 4. 自动工具生成 + 自修复

当现有 36 个工具无法满足需求时，触发 `auto_tool`：

```
用户: "帮我计算这个流域的重现期降雨强度"
  │
  ├─ 现有工具无匹配 → 触发 auto_tool
  ▼
LLM 生成 Python 代码 → 沙箱执行
  │
  ├─ 执行成功 → 返回结果
  └─ 执行失败 → 自修复引擎
       │
       ▼
  将 完整错误堆栈 + 原始代码 发送给 LLM
       │
       ▼
  LLM 生成修复代码 → 重新执行 (最多重试 2 次)
```

### 5. 思维树推理 (Tree-of-Thought)

面对复杂、模糊的请求，系统生成 3 条候选方案，每条独立评估打分，选择最优路径：

```
用户: "这个区域怎么防治山洪？"
  │
  ├─ 方案 A: 地形分析→汇流计算→工程建议 (score: 8)  ← 选中
  ├─ 方案 B: 历史灾情查询→风险分区→预警方案 (score: 7)
  └─ 方案 C: 气象预报→径流模拟→应急响应  (score: 6)
```

### 6. 物理常识注入 + 水力学校验

系统在推理前注入水利领域常识，增强 LLM 准确性：

```
"黄河流域年均降水量 300-800mm"
"曼宁糙率: 混凝土管 0.013, 土渠 0.025"
"SCS-CN: 混凝土 98, 草地 60-70, 林地 35-60"
"设计暴雨重现期: 城市排水 2-10年, 防洪 50-100年"
```

执行后还有**水力学物理校验**：流速 0-15 m/s、水深正值、坡度 0-90°。

---

## ◆ 可靠性基础设施

| 模块 | 实现 | 说明 |
|------|------|------|
| **熔断器** | 3 次失败触发，120s 冷却 | 防止故障雪崩 |
| **LRU 缓存** | 200 条容量，5min TTL | 相同参数直接返回 |
| **全链路追踪** | TraceSpan 记录路由/LLM/工具/渲染 | 可观测性 |
| **自进化路由** | 记录每次路由结果，统计准确率 | 自动学习高频模式 |
| **智能体记忆** | SQLite (episodes/facts/procedures) | 跨会话经验积累 |
| **数字孪生桥梁** | 可扩展数据源注册表 | DEM + 气象 + 自定义 |

---

## ◆ 前端 · Vue 3 架构

### 技术栈

| 层级 | 技术 | 职责 |
|------|------|------|
| **框架** | Vue 3.5 + TypeScript | Composition API，类型安全 |
| **构建** | Vite 8 (rolldown) | 亚秒级 HMR，生产级 tree-shaking |
| **状态** | Pinia (3 stores) | 消息流 / Leaflet 图层 / Three.js 场景 |
| **样式** | TailwindCSS v3 + CSS Variables | 暗色毛玻璃主题 |
| **地图** | Leaflet + CartoDB Dark | GeoJSON 叠加、图层管理、坐标拾取 |
| **3D** | Three.js r160 + OrbitControls | 海拔着色地形、天空穹顶 Shader |
| **水动力** | Three.js + GLSL ShaderMaterial | TIN 网格水面、顶点位移波浪、时间线播放器 |
| **通信** | EventSource (SSE) | 12 种事件类型实时推送 |
| **编排** | WorkflowEditor (DAG) | 拖拽画布、SVG Bezier 连线、模板系统 |

### 18+ 工具渲染策略

每种工具类型拥有独立渲染函数，返回 `{ html, mapActions[] }`：

| 策略 | 输出 |
|------|------|
| `dem_analyze` | SVG 仪表盘 + 高程/坡度卡片 |
| `buffer` / `overlay` | GeoJSON 地图叠加 + 可视化 |
| `design_storm` | SVG 时间序列降雨图表 |
| `flood_inundation` | GeoJSON 淹没范围 + 统计表 |
| `watershed_delineate` | 流域边界 + 河网叠加 |
| `flow_accumulation` | 汇流累积热力图 |
| `swmm_simulate` | SWMM 时间序列曲线 |
| `hydrodynamic_2d_sim` | Three.js 3D 水动力自动播放 |
| `scatter_interpolate` | 插值热力图 image overlay |
| `hydrodynamic_2d_sim` | TIN mesh + GLSL 波浪动画 |
| Generic fallback | 表格 / 代码块 / JSON / SVG 图表 |

### SSE 事件流 (12 种类型)

```
start           → 会话初始化，获取 conv_id
thinking_start  → 创建思考框 (Spinner + Agent + Label)
thinking        → 添加思考行 (6 种样式分类)
thinking_end    → 关闭思考框 (✓ complete)
tool_start      → 工具开始 (⏳ running + 实时计时)
tool_end        → 工具结束 (✅ ok / ❌ error)
tool_result     → 工具结果 + 地图动作 + HTML 渲染
tool_error      → 工具错误信息
divider         → 分隔线 (两侧渐变)
chain_suggestion → 推荐下一步操作
text            → LLM 文本回复
done            → 推理完成
```

---

## ◆ 能力矩阵 · 36 工具

### 🗺️ GIS 空间分析 (8 tools)

| 工具 | 说明 |
|------|------|
| `spatial_query` | 空间关系查询 (intersects/contains/within/...) |
| `buffer` | 几何缓冲区分析 |
| `overlay` | 叠加分析 (intersection/union/difference) |
| `coordinate_transform` | 坐标转换 (EPSG:4544 ↔ WGS84) |
| `geometry_properties` | 几何属性 (面积/周长/质心) |
| `read_vector` / `write_vector` | 矢量数据读写 |
| `validate_data` | 数据质量校验 |
| `import_network` | 管网数据导入 |

### 🏔️ Raster 地形分析 (5 tools)

| 工具 | 说明 |
|------|------|
| `dem_analyze` | DEM 高程/坡度/坡向采样 (0.5m分辨率) |
| `flow_accumulation` | D8 流向 + 汇流累积 |
| `watershed_delineate` | Strahler 分级流域自动提取 |
| `terrain_profile` | 地形剖面线 |
| `scatter_interpolate` | 散点插值 (Kriging/IDW/RBF) |

### 💧 Hydro 水文建模 (5 tools)

| 工具 | 说明 |
|------|------|
| `design_storm` | 芝加哥设计暴雨 (任意重现期) |
| `runoff_compute` | SCS-CN 径流计算 |
| `swmm_simulate` | PySWMM 排水管网模拟 |
| `calibrate_suggest` | 模型率定建议 |
| `hydrodynamic_2d_sim` | **2D 水动力 TIN 网格模拟** (GLSL 实时渲染) |

### 🌊 Flood 内涝分析 (5 tools)

| 工具 | 说明 |
|------|------|
| `flood_inundation_map` | 洪水淹没范围 |
| `flood_assessment` | 洪水风险评估 |
| `drainage_assessment` | 排水能力校核 |
| `flood_warning` | 洪水预警等级 |
| `flood_risk_zones` | 洪水风险分区 |

### 📚 Knowledge + Data + Map (13 tools)

| 工具 | 服务 | 说明 |
|------|------|------|
| `get_parameter` | Knowledge | 曼宁糙率/SCS-CN/管材/水泵/海绵/排水参数 |
| `explain_concept` | Knowledge | 水利专业概念解释 |
| `search` | Knowledge | 知识库语义搜索 |
| `get_standard` | Knowledge | 水利标准规范 (GB50014等) |
| `render_map` | Map | 地图渲染 |
| `weather_forecast` | Map | 气象预报 (Open-Meteo) |
| `satellite_search` | Map | 卫星影像检索 |
| `spatial_knowledge_query` | Map | 空间知识图谱 |
| `auto_tool` | Internal | LLM 自动生成工具 (兜底) |
| `image_analysis` | Internal | 图片理解 (GLM-4V) |

---

## ◆ 智能体编排 · Workflow DAG

WorkflowEditor 提供可视化 DAG 编排能力：

- **拖拽式画布** — 7 个 Agent 工具面板，拖到画布即创建节点
- **SVG Bezier 连线** — 端口连接，数据流可视化
- **节点状态机** — idle → running → done/error，实时状态
- **预置模板** — 地形分析链、洪水分析链，一键加载
- **localStorage 持久化** — 保存/加载/删除
- **拓扑排序执行** — Run 按钮按依赖关系依次执行

---

## ◆ 水动力 3D 可视化

2D 水动力模拟结果通过自定义 GLSL Shader 在 Three.js 中实时渲染：

```
TIN 三角网格 (tin_vertex_lng/lat/elev + tin_simplices)
  │
  ├─ 顶点位置 = DEM 高程 + 水深偏移
  ├─ 顶点颜色 = 深度渐变 (深蓝→浅蓝→白色泡沫)
  ▼
ShaderMaterial (GLSL)
  ├─ 顶点着色器: sin/cos 波浪位移
  └─ 片元着色器: 深度着色 + 菲涅尔反射 + 泡沫
  ▼
时间线播放器: ▶Play ⏸Pause | Seek拖动 | 1x/2x/4x变速 | 自动播放
```

---

## ◆ 快速启动

### 环境要求

- Python 3.10+
- Node.js 18+
- `ZHIPUAI_API_KEY` 环境变量

### 启动

```bash
# 1. API Key
set ZHIPUAI_API_KEY=your_key_here          # Windows
export ZHIPUAI_API_KEY=your_key_here       # Linux/Mac

# 2. Python 依赖
pip install fastapi uvicorn httpx zhipuai rasterio geopandas shapely \
            numpy scipy fiona pyswmm structlog python-dotenv

# 3. 启动后端 (7 MCP + Web Server)
python web/server.py
# → Web  :3000  GIS  :5001  Data :5002  Knowledge :5003
# → Map  :5004  Hydro:5005  Flood:5006  Raster    :5007

# 4. 启动前端
cd web/frontend
npm install && npm run dev
# → Vite :5173  (代理 /api/* → :3000)
```

### 生产构建

```bash
cd web/frontend && npm run build    # → dist/ (~836KB JS, 236KB gzip)
```

---

## ◆ 项目结构

```
S-AI/
├── web/
│   ├── server.py                    # 后端主服务 (1940行)
│   │   ├── 三层路由 (L1/L2/L3)      │   ├── 辩论验证 (3角色)
│   │   ├── ReAct 推理 (8步)         │   ├── 思维树 (ToT)
│   │   ├── 自动工具生成 + 自修复     │   ├── 熔断器 + LRU缓存
│   │   ├── 全链路追踪               │   ├── 自进化路由学习
│   │   ├── 智能体记忆 (SQLite)      │   ├── 数字孪生桥梁
│   │   ├── 常识注入 + 物理校验      │   ├── 图片理解 (GLM-4V)
│   │   └── 对话持久化 + 文件上传
│   │
│   ├── index.html                   # 原版前端 (2596行, 参考)
│   └── frontend/                    # Vue 3 前端
│       ├── vite.config.ts
│       └── src/
│           ├── App.vue              # 三栏 + 事件流 + Workflow
│           ├── components/          # TopBar SideBar MapPanel ChatPanel WorkflowEditor
│           ├── stores/              # chat.ts map.ts three.ts
│           ├── composables/         # useSSE useToolRenderer useServices
│           ├── types/               # SSEEvent ChatMessage ToolResult MapLayerInfo
│           └── styles/              # variables.css main.css
│
├── data/
│   ├── LBH_DEM_v2_0.5m_EPSG4544.tif  # 3GB DEM
│   ├── agent_memory.db              # 智能体记忆
│   ├── conversations.db             # 对话持久化
│   └── generated_tools/             # LLM 生成工具
├── .env                             # ZHIPUAI_API_KEY
└── README.md
```

---

## ◆ 设计决策 · Why

### 为什么选择 MCP 微服务

每个空间领域拥有完全不同的计算范式和依赖链。MCP 拆分带来：**故障隔离**（GIS 崩溃不影响水文模拟）、**独立扩展**（DEM 计算可单独部署）、**工具热插拔**（新增工具无需重启主服务）、**熔断保护**（单工具故障不拖垮推理链）。

### 为什么用 ReAct 而非 Function Calling

Function Calling 一次只能选一个工具。水利分析天然是多步推理：先看地形、再算汇流、然后评估风险。ReAct 循环允许 LLM 每步观察上一步结果，动态调整策略，形成真正的推理链。

### 为什么用 ShaderMaterial 做水动力

MeshPhysicalMaterial 无法实现实时水面波动。自定义 GLSL Shader（顶点位移 + 深度着色 + 菲涅尔反射 + 泡沫效果）实现 TIN 网格实时可视化，每帧更新顶点位置和颜色。

### 为什么选择 Vue 3

前端管理复杂的实时状态流（SSE 12 种事件、思考过程、工具状态、GeoJSON 渲染）。Vue 3 Composition API + Pinia 提供最直观的响应式状态管理，TypeScript 类型推导让 SSE→UI 整条数据链路清晰可追踪。

---

## ◆ License

MIT License — 自由使用，欢迎贡献。

---

<p align="center">
  <sub>由 <strong>LUOBIN-PI Research Lab</strong> 倾力打造</sub><br>
  <sub>让空间智能，触手可及</sub>
</p>
