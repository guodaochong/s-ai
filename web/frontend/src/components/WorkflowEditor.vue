<script setup lang="ts">
import { ref, reactive, computed } from 'vue'

const showEditor = ref(false)

interface WfNode {
  id: string
  agent: string
  tool: string
  label: string
  color: string
  x: number
  y: number
  status: 'idle' | 'running' | 'done' | 'error'
  config: Record<string, any>
}
interface WfEdge {
  id: string
  from: string
  to: string
  status: 'idle' | 'active' | 'done' | 'error'
}

const nodes = reactive<WfNode[]>([])
const edges = reactive<WfEdge[]>([])
let nextId = 1
let selected: string | null = null
let dragging: { nodeId: string; offsetX: number; offsetY: number } | null = null
let connecting: { fromId: string; startX: number; startY: number } | null = null
const mousePos = reactive({ x: 0, y: 0 })
const statusText = ref('')
const showList = ref(false)
const canvasRef = ref<HTMLDivElement>()

const WF_TOOLS: Record<string, { label: string; color: string; tools: { id: string; label: string }[] }> = {
  gis: { label: 'GIS 空间分析', color: '#00ff88', tools: [
    { id: 'buffer', label: '缓冲区分析' }, { id: 'spatial_query', label: '空间查询' },
    { id: 'overlay', label: '叠加分析' }, { id: 'geometry_properties', label: '几何属性' },
  ] },
  data: { label: 'Data 数据管理', color: '#ffaa00', tools: [
    { id: 'import_network', label: '管网导入' }, { id: 'validate_data', label: '数据验证' },
  ] },
  knowledge: { label: 'Knowledge 知识库', color: '#cc88ff', tools: [
    { id: 'get_parameter', label: '参数查询' }, { id: 'search_standard', label: '标准检索' },
  ] },
  map: { label: 'Map 可视化', color: '#ff8800', tools: [
    { id: 'render_map', label: '地图渲染' }, { id: 'export_data', label: '数据导出' },
  ] },
  hydro: { label: 'Hydro 水文建模', color: '#00ccff', tools: [
    { id: 'design_storm', label: '设计暴雨' }, { id: 'runoff_compute', label: 'SCS-CN径流' },
    { id: 'swmm_simulate', label: 'SWMM模拟' }, { id: 'hydrodynamic_2d_sim', label: '2D水动力' },
  ] },
  flood: { label: 'Flood 内涝分析', color: '#ff4444', tools: [
    { id: 'flood_inundation_map', label: '淹没分析' }, { id: 'flood_warning', label: '洪水预警' },
    { id: 'flood_risk_zones', label: '风险分区' },
  ] },
  raster: { label: 'Raster 地形分析', color: '#44ff44', tools: [
    { id: 'dem_analyze', label: 'DEM坡度分析' }, { id: 'flow_accumulation', label: '河网提取' },
    { id: 'watershed_delineate', label: '流域提取' }, { id: 'terrain_profile', label: '地形剖面' },
    { id: 'dem_render', label: '地形渲染' },
  ] },
}

function toggle() {
  showEditor.value = !showEditor.value
}

function addNode(agent: string, tool: string, x: number, y: number) {
  const g = WF_TOOLS[agent]
  const t = g.tools.find(t => t.id === tool)
  const id = 'n' + (nextId++)
  const node: WfNode = { id, agent, tool, label: t ? t.label : tool, color: g.color, x: Math.max(0, x), y: Math.max(0, y), status: 'idle', config: {} }
  nodes.push(node)
  return node
}

function removeNode(id: string) {
  const idx = nodes.findIndex(n => n.id === id)
  if (idx >= 0) nodes.splice(idx, 1)
  for (let i = edges.length - 1; i >= 0; i--) {
    if (edges[i].from === id || edges[i].to === id) edges.splice(i, 1)
  }
  if (selected === id) selected = null
}

function addEdge(fromId: string, toId: string) {
  if (fromId === toId) return
  if (edges.some(e => e.from === fromId && e.to === toId)) return
  const id = 'e' + (nextId++)
  edges.push({ id, from: fromId, to: toId, status: 'idle' })
}

function clearAll() {
  nodes.splice(0)
  edges.splice(0)
  selected = null
  statusText.value = ''
}

function loadTemplate(name: string) {
  clearAll()
  const templates: Record<string, Partial<WfNode>[]> = {
    terrain: [
      { agent: 'raster', tool: 'dem_analyze', label: 'DEM坡度分析', x: 40, y: 40 },
      { agent: 'raster', tool: 'flow_accumulation', label: '河网提取', x: 220, y: 40 },
      { agent: 'raster', tool: 'watershed_delineate', label: '流域提取', x: 220, y: 160 },
      { agent: 'raster', tool: 'dem_render', label: '地形渲染', x: 40, y: 160 },
    ],
    flood: [
      { agent: 'raster', tool: 'dem_analyze', label: 'DEM分析', x: 40, y: 40 },
      { agent: 'flood', tool: 'flood_inundation_map', label: '淹没模拟', x: 220, y: 40 },
      { agent: 'flood', tool: 'flood_warning', label: '洪水预警', x: 220, y: 160 },
      { agent: 'flood', tool: 'flood_risk_zones', label: '风险分区', x: 40, y: 160 },
    ],
  }
  const tpl = templates[name]
  if (!tpl) return
  tpl.forEach(t => {
    const g = WF_TOOLS[t.agent!]
    const id = 'n' + (nextId++)
    nodes.push({ id, agent: t.agent!, tool: t.tool!, label: t.label || t.tool!, color: g.color, x: t.x || 0, y: t.y || 0, status: 'idle', config: {} })
  })
  const edgePairs = [[0, 1], [0, 3], [1, 2], [3, 2]]
  edgePairs.forEach(([a, b]) => {
    if (nodes[a] && nodes[b]) addEdge(nodes[a].id, nodes[b].id)
  })
  statusText.value = 'Template: ' + name
}

function saveWorkflow() {
  const name = prompt('方案名称（用于对话调用，如"地形分析"）：', '自定义流程')
  if (!name) return
  const data = {
    name,
    nodes: nodes.map(n => ({ id: n.id, agent: n.agent, tool: n.tool, label: n.label, color: n.color, x: n.x, y: n.y, config: n.config })),
    edges: edges.map(e => ({ id: e.id, from: e.from, to: e.to })),
  }
  const all = JSON.parse(localStorage.getItem('wf_workflows') || '{}')
  all[name] = data
  localStorage.setItem('wf_workflows', JSON.stringify(all))
  localStorage.setItem('wf_save', JSON.stringify(data))
  statusText.value = 'Saved: ' + name + ' ✓'
}

function listWorkflows() {
  showList.value = !showList.value
}

function deleteWorkflow(name: string) {
  const all = JSON.parse(localStorage.getItem('wf_workflows') || '{}')
  delete all[name]
  localStorage.setItem('wf_workflows', JSON.stringify(all))
}

function getSavedWorkflows() {
  return Object.entries(JSON.parse(localStorage.getItem('wf_workflows') || '{}')) as [string, any][]
}

function selectNode(id: string) {
  selected = id
}

function onNodeMouseDown(e: MouseEvent, nodeId: string) {
  e.stopPropagation()
  selected = nodeId
  const node = nodes.find(n => n.id === nodeId)
  if (!node) return
  dragging = { nodeId, offsetX: e.clientX - node.x, offsetY: e.clientY - node.y }
}

function onPortMouseDown(e: MouseEvent, nodeId: string) {
  e.stopPropagation()
  connecting = { fromId: nodeId, startX: 0, startY: 0 }
}

function onCanvasMouseMove(e: MouseEvent) {
  if (dragging) {
    const node = nodes.find(n => n.id === dragging!.nodeId)
    if (node) {
      node.x = Math.max(0, e.clientX - dragging!.offsetX)
      node.y = Math.max(0, e.clientY - dragging!.offsetY)
    }
  }
  mousePos.x = e.clientX
  mousePos.y = e.clientY
}

function onCanvasMouseUp(e: MouseEvent) {
  if (connecting) {
    const target = (e.target as HTMLElement).closest('[data-node-id]')
    if (target) {
      const toId = target.getAttribute('data-node-id')!
      addEdge(connecting.fromId, toId)
    }
    connecting = null
  }
  dragging = null
}

function onCanvasClick(e: MouseEvent) {
  if (e.target === canvasRef.value || (e.target as HTMLElement).tagName === 'svg') {
    selected = null
  }
}

function onDragOver(e: DragEvent) {
  e.preventDefault()
  e.dataTransfer!.dropEffect = 'copy'
}

function onDrop(e: DragEvent) {
  e.preventDefault()
  try {
    const raw = e.dataTransfer!.getData('application/json')
    const d = JSON.parse(raw)
    const rect = canvasRef.value!.getBoundingClientRect()
    addNode(d.agent, d.tool, e.clientX - rect.left - 70, e.clientY - rect.top - 20)
  } catch {}
}

function onToolDragStart(e: DragEvent, agent: string, tool: string) {
  e.dataTransfer!.setData('application/json', JSON.stringify({ agent, tool }))
  e.dataTransfer!.effectAllowed = 'copy'
}

async function runWorkflow() {
  const sorted = topologicalSort()
  statusText.value = 'Running...'
  for (const node of sorted) {
    node.status = 'running'
    const incomingEdges = edges.filter(e => e.to === node.id)
    incomingEdges.forEach(e => e.status = 'active')
    await new Promise<void>(resolve => {
      const url = `/api/tools/call?server=${node.agent}&tool=${node.tool}&args=${encodeURIComponent(JSON.stringify(node.config))}`
      fetch(url).then(r => r.json()).then(data => {
        node.status = data.error ? 'error' : 'done'
        incomingEdges.forEach(e => e.status = data.error ? 'error' : 'done')
        resolve()
      }).catch(() => {
        node.status = 'error'
        incomingEdges.forEach(e => e.status = 'error')
        resolve()
      })
    })
  }
  statusText.value = 'Done'
}

function topologicalSort(): WfNode[] {
  const visited = new Set<string>()
  const result: WfNode[] = []
  function visit(id: string) {
    if (visited.has(id)) return
    visited.add(id)
    edges.filter(e => e.from === id).forEach(e => visit(e.to))
    const node = nodes.find(n => n.id === id)
    if (node) result.unshift(node)
  }
  nodes.forEach(n => visit(n.id))
  return result
}

function edgePath(edge: { from: string; to: string }) {
  const from = nodes.find(n => n.id === edge.from)
  const to = nodes.find(n => n.id === edge.to)
  if (!from || !to) return ''
  const x1 = from.x + 140
  const y1 = from.y + 25
  const x2 = to.x
  const y2 = to.y + 25
  const cx = Math.abs(x2 - x1) * 0.5
  return `M ${x1} ${y1} C ${x1 + cx} ${y1}, ${x2 - cx} ${y2}, ${x2} ${y2}`
}

const tempEdgePath = computed(() => {
  if (!connecting) return ''
  const from = nodes.find(n => n.id === connecting!.fromId)
  if (!from) return ''
  const x1 = from.x + 140
  const y1 = from.y + 25
  return `M ${x1} ${y1} L ${mousePos.x} ${mousePos.y}`
})

defineExpose({ toggle, loadTemplate })
</script>

<template>
  <Teleport to="body">
    <div :class="['wf-editor', { hidden: !showEditor }]">
      <div class="wf-header">
        <h2>⚙️ WORKFLOW EDITOR</h2>
        <button class="wf-close" @click="toggle">✕</button>
      </div>
      <div class="wf-body">
        <div class="wf-palette">
          <template v-for="(g, agent) in WF_TOOLS" :key="agent">
            <div class="wf-pal-group">
              <div class="wf-pal-group-title" :style="{ color: g.color }">
                <span class="wf-pal-dot" :style="{ background: g.color }" />
                {{ g.label }}
              </div>
              <div
                v-for="t in g.tools" :key="t.id"
                class="wf-pal-item"
                draggable="true"
                @dragstart="onToolDragStart($event, agent, t.id)"
              >
                <span class="wf-pal-dot" :style="{ background: g.color }" />
                {{ t.label }}
              </div>
            </div>
          </template>
        </div>
        <div class="wf-canvas-wrap">
          <div
            ref="canvasRef"
            class="wf-canvas"
            @mousemove="onCanvasMouseMove"
            @mouseup="onCanvasMouseUp"
            @click="onCanvasClick"
            @dragover="onDragOver"
            @drop="onDrop"
          >
            <svg>
              <path
                v-for="edge in edges" :key="edge.id"
                :class="['wf-edge-path', edge.status]"
                :d="edgePath(edge)"
              />
              <path v-if="connecting" class="wf-temp-edge" :d="tempEdgePath" />
            </svg>
            <div
              v-for="node in nodes" :key="node.id"
              :class="['wf-node', node.status, { selected: selected === node.id }]"
              :style="{ left: node.x + 'px', top: node.y + 'px' }"
              :data-node-id="node.id"
              @mousedown="onNodeMouseDown($event, node.id)"
            >
              <div class="wf-node-title">
                <span class="wf-pal-dot" :style="{ background: node.color }" />
                {{ node.label }}
              </div>
              <div class="wf-node-sub">{{ node.agent }}.{{ node.tool }}</div>
              <button class="wf-node-del" @click.stop="removeNode(node.id)">✕</button>
              <div class="wf-port in" @mousedown.stop="onPortMouseDown($event, node.id)" />
              <div class="wf-port out" @mousedown.stop="connecting = { fromId: node.id, startX: 0, startY: 0 }" />
            </div>
          </div>
        </div>
      </div>
      <div class="wf-toolbar">
        <button class="wf-btn primary" @click="runWorkflow">▶ Run</button>
        <button class="wf-btn" @click="loadTemplate('terrain')">🏔️ 地形</button>
        <button class="wf-btn" @click="loadTemplate('flood')">🌊 洪水</button>
        <button class="wf-btn" @click="saveWorkflow">💾</button>
        <button class="wf-btn" @click="listWorkflows">📋 方案</button>
        <button class="wf-btn danger" @click="clearAll">🗑</button>
        <span class="wf-status">{{ statusText }}</span>
        <div v-if="showList" class="wf-list">
          <div class="wf-list-title">已保存方案 ({{ getSavedWorkflows().length }}):</div>
          <div v-if="getSavedWorkflows().length === 0" class="wf-list-empty">暂无，点击💾保存当前编排</div>
          <div v-for="[name, tpl] in getSavedWorkflows()" :key="name" class="wf-list-item">
            <span class="wf-list-name">{{ name }} ({{ tpl.nodes?.length || 0 }}节点)</span>
            <span class="wf-list-del" @click="deleteWorkflow(name)">✕</span>
          </div>
        </div>
      </div>
    </div>

    <button class="wf-toggle" @click="toggle" title="Workflow Editor">🧠</button>
  </Teleport>
</template>

<style scoped>
.wf-editor {
  position: fixed;
  right: 0;
  top: 0;
  width: 520px;
  height: 100vh;
  z-index: 2000;
  background: rgba(6, 10, 19, .95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-left: 1px solid rgba(0, 212, 255, .1);
  display: flex;
  flex-direction: column;
  transform: translateX(0);
  transition: transform .35s cubic-bezier(.4, 0, .2, 1);
  box-shadow: -8px 0 40px rgba(0, 0, 0, .5);
}
.wf-editor.hidden {
  transform: translateX(520px);
}
.wf-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: rgba(13, 19, 33, .6);
  border-bottom: var(--glass-border);
}
.wf-header h2 {
  font-size: 13px;
  letter-spacing: 3px;
  color: var(--accent);
  font-family: 'JetBrains Mono', monospace;
  margin: 0;
  text-shadow: 0 0 12px rgba(0, 212, 255, .3);
}
.wf-close {
  background: none;
  border: 1px solid var(--border);
  color: var(--text-dim);
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 14px;
}
.wf-close:hover { color: var(--accent); border-color: rgba(0, 212, 255, .3); }
.wf-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}
.wf-palette {
  width: 190px;
  background: rgba(13, 19, 33, .5);
  border-right: var(--glass-border);
  overflow-y: auto;
  padding: 8px;
  flex-shrink: 0;
}
.wf-pal-group { margin-bottom: 8px; }
.wf-pal-group-title {
  font-size: 10px;
  font-weight: 700;
  padding: 6px 6px 4px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.wf-pal-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.wf-pal-item {
  padding: 5px 8px 5px 20px;
  font-size: 10px;
  color: var(--text-dim);
  cursor: grab;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all .2s;
}
.wf-pal-item:hover {
  background: rgba(0, 212, 255, .06);
  color: var(--text);
}
.wf-canvas-wrap {
  flex: 1;
  position: relative;
  overflow: hidden;
}
.wf-canvas {
  position: absolute;
  inset: 0;
  cursor: default;
  background-image: radial-gradient(circle, rgba(0, 212, 255, .06) 1px, transparent 1px);
  background-size: 24px 24px;
}
.wf-canvas svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}
.wf-edge-path {
  fill: none;
  stroke: rgba(100, 116, 139, .4);
  stroke-width: 2;
  transition: stroke .2s;
}
.wf-edge-path.active { stroke: var(--accent); stroke-width: 2.5; filter: drop-shadow(0 0 4px rgba(0, 212, 255, .4)); }
.wf-edge-path.done { stroke: var(--accent3); }
.wf-edge-path.error { stroke: var(--danger); }
.wf-temp-edge { fill: none; stroke: var(--accent); stroke-width: 2; stroke-dasharray: 6 3; opacity: .7; }
.wf-node {
  position: absolute;
  min-width: 130px;
  max-width: 180px;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1.5px solid var(--border);
  background: rgba(22, 33, 52, .8);
  backdrop-filter: blur(6px);
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  cursor: move;
  user-select: none;
  transition: box-shadow .25s;
  z-index: 1;
  box-shadow: var(--shadow-sm);
}
.wf-node:hover { box-shadow: 0 0 20px rgba(0, 212, 255, .15), var(--shadow-md); }
.wf-node.running { border-color: var(--accent); box-shadow: 0 0 24px rgba(0, 212, 255, .35); }
.wf-node.done { border-color: var(--accent3); box-shadow: 0 0 12px rgba(16, 185, 129, .2); }
.wf-node.error { border-color: var(--danger); box-shadow: 0 0 12px rgba(239, 68, 68, .2); }
.wf-node.selected { border-color: var(--accent2); box-shadow: 0 0 20px rgba(124, 58, 237, .3); }
.wf-node-title { font-weight: 700; color: var(--text); margin-bottom: 2px; display: flex; align-items: center; gap: 5px; }
.wf-node-sub { font-size: 9px; color: var(--text-dim); }
.wf-node-del {
  position: absolute; top: -8px; right: -8px; width: 18px; height: 18px;
  border-radius: 50%; background: var(--danger); color: #fff; border: none;
  font-size: 10px; cursor: pointer; display: none; align-items: center;
  justify-content: center; z-index: 3; box-shadow: 0 2px 6px rgba(239, 68, 68, .4);
}
.wf-node:hover .wf-node-del { display: flex; }
.wf-port {
  position: absolute; width: 12px; height: 12px; border-radius: 50%;
  border: 2px solid rgba(100, 116, 139, .4); background: var(--bg-deep);
  cursor: crosshair; z-index: 2; transition: all .2s;
}
.wf-port:hover { border-color: var(--accent); background: var(--accent); transform: scale(1.4); box-shadow: 0 0 8px var(--accent); }
.wf-port.in { left: -7px; top: 50%; margin-top: -6px; }
.wf-port.out { right: -7px; top: 50%; margin-top: -6px; }
.wf-toolbar {
  display: flex;
  gap: 8px;
  padding: 8px 16px;
  background: rgba(13, 19, 33, .6);
  border-top: var(--glass-border);
  align-items: center;
  flex-shrink: 0;
  flex-wrap: wrap;
}
.wf-btn {
  padding: 7px 14px; border-radius: 6px; border: 1px solid var(--border);
  background: var(--bg-card); color: var(--text); font-size: 11px; cursor: pointer;
  font-family: 'JetBrains Mono', monospace; display: flex; align-items: center;
  gap: 5px; transition: all .2s;
}
.wf-btn:hover { border-color: rgba(0, 212, 255, .3); color: var(--accent); box-shadow: 0 0 8px rgba(0, 212, 255, .1); }
.wf-btn.primary { background: var(--gradient-accent); border: none; color: #fff; font-weight: 600; box-shadow: 0 2px 12px rgba(0, 212, 255, .2); }
.wf-btn.primary:hover { box-shadow: 0 4px 20px rgba(0, 212, 255, .35); transform: translateY(-1px); }
.wf-btn.danger { border-color: rgba(239, 68, 68, .2); color: var(--danger); }
.wf-btn.danger:hover { background: rgba(239, 68, 68, .1); }
.wf-status { margin-left: auto; font-size: 10px; color: var(--text-dim); font-family: 'JetBrains Mono', monospace; }
.wf-list { width: 100%; margin-top: 6px; max-height: 120px; overflow-y: auto; font-size: 11px; }
.wf-list-title { color: var(--text-dim); margin-bottom: 4px; }
.wf-list-empty { color: var(--text-dim); }
.wf-list-item { display: flex; align-items: center; gap: 6px; padding: 3px 0; border-bottom: 1px solid var(--border); }
.wf-list-name { color: var(--accent); cursor: pointer; flex: 1; }
.wf-list-del { color: #ff4444; cursor: pointer; font-size: 10px; }
.wf-toggle {
  position: fixed;
  left: 8px;
  top: 8px;
  z-index: 9999;
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg-panel);
  color: var(--text);
  cursor: pointer;
  font-size: 14px;
  display: grid;
  place-items: center;
  transition: all .2s;
  box-shadow: 0 2px 8px rgba(0, 0, 0, .3);
}
.wf-toggle:hover { border-color: var(--accent); color: var(--accent); box-shadow: var(--glow); }
</style>
