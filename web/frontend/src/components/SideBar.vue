<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useMapStore } from '@/stores/map'
import { useServices } from '@/composables/useServices'

const API = '/api'
const chatStore = useChatStore()
const mapStore = useMapStore()
const { services, serviceCount } = useServices()

const agents = [
  { key: 'router', emoji: '💡', name: 'Router 总指挥', caps: '意图路由 · 任务分解 · 结果整合' },
  { key: 'gis', emoji: '🗺️', name: 'GIS 空间分析', caps: '缓冲区 · 叠加 · 空间查询 · 坐标转换' },
  { key: 'knowledge', emoji: '📚', name: 'Knowledge 知识库', caps: '参数查询 · 标准检索 · 概念解释' },
  { key: 'data', emoji: '🛠️', name: 'Data 数据管理', caps: '数据导入 · 质量检查 · 格式转换' },
  { key: 'map', emoji: '📊', name: 'Map 可视化', caps: '地图渲染 · 专题图 · 过程线' },
  { key: 'hydro', emoji: '🌊', name: 'Hydro 水文建模', caps: '设计暴雨 · SCS-CN · SWMM · 率定' },
  { key: 'flood', emoji: '💧', name: 'Flood 内涝分析', caps: '淹没评估 · 排水能力 · 预警 · 风险分区' },
  { key: 'raster', emoji: '⛰️', name: 'Raster 地形分析', caps: 'DEM坡度 · 汇流累积 · 流域提取' },
]

const activeAgent = ref('router')
const convList = ref<{ id: number; title: string }[]>([])

function selectAgent(key: string) {
  activeAgent.value = key
}

function loadConvList() {
  fetch(`${API}/conversations`).then(r => r.json()).then(d => {
    convList.value = d.conversations || []
  }).catch(() => {})
}

function switchConversation(id: number) {
  chatStore.currentConvId = String(id)
  localStorage.setItem('sai_conv_id', String(id))
  chatStore.messages.splice(0)
  chatStore.toolResults.splice(0)
  chatStore.toolHtmlParts.splice(0)
  chatStore.thinkingLines.splice(0)
  mapStore.clearAll()
  fetch(`${API}/conversations/${id}/messages`).then(r => r.json()).then(d => {
    if (!d.messages) return
    d.messages.forEach((m: any) => {
      if (m.role === 'user') {
        chatStore.addUserMessage(m.content)
      } else if (m.role === 'assistant') {
        chatStore.addBotMessage(m.content)
      }
    })
  }).catch(() => {})
  loadConvList()
}

function deleteConversation(id: number) {
  if (!confirm('删除此对话？')) return
  fetch(`${API}/conversations/${id}`, { method: 'DELETE' }).then(() => loadConvList())
  if (String(id) === chatStore.currentConvId) {
    newConversation()
  }
}

function newConversation() {
  const title = '对话 ' + new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  fetch(`${API}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  }).then(r => r.json()).then(d => {
    chatStore.currentConvId = String(d.id)
    localStorage.setItem('sai_conv_id', String(d.id))
    chatStore.messages.splice(0)
    chatStore.toolResults.splice(0)
    chatStore.toolHtmlParts.splice(0)
    chatStore.thinkingLines.splice(0)
    chatStore.isStreaming = false
    mapStore.clearAll()
    loadConvList()
  })
}

onMounted(() => {
  loadConvList()
  const savedId = localStorage.getItem('sai_conv_id')
  if (savedId) switchConversation(Number(savedId))
})
</script>

<template>
  <aside class="sidebar">
    <h3>Agent 面板</h3>
    <div
      v-for="a in agents" :key="a.key"
      :class="['agent-card', { active: activeAgent === a.key }]"
      @click="selectAgent(a.key)"
    >
      <div class="name"><span class="emoji">{{ a.emoji }}</span> {{ a.name }}</div>
      <div class="caps">{{ a.caps }}</div>
    </div>

    <h3 style="margin-top: auto">对话历史</h3>
    <div style="padding: 0 8px 4px; display: flex; gap: 4px">
      <button class="new-conv-btn" @click="newConversation">＋ 新对话</button>
    </div>
    <div class="conv-list">
      <div
        v-for="c in convList" :key="c.id"
        :class="['conv-item', { active: String(c.id) === chatStore.currentConvId }]"
      >
        <span class="conv-title" @click="switchConversation(c.id)">{{ c.title || '对话 ' + c.id }}</span>
        <span class="conv-del" @click.stop="deleteConversation(c.id)">✕</span>
      </div>
    </div>

    <h3>系统信息</h3>
    <div class="sys-info">
      <div>MCP Servers: <span class="val-green">{{ serviceCount.healthy }}</span>/{{ serviceCount.total }}</div>
      <div>Tools: <span class="val-cyan">{{ serviceCount.tools }}</span></div>
      <div>Events: <span class="val-purple">{{ chatStore.eventCount }}</span></div>
      <div>图层: <span class="val-cyan">{{ mapStore.layers.length }}</span></div>
    </div>

    <h3>服务状态</h3>
    <div class="svc-list">
      <div v-for="svc in services" :key="svc.name" class="svc-row">
        <span class="svc-dot" :style="{ background: svc.healthy ? '#10b981' : '#ef4444' }" />
        <span class="svc-name">{{ svc.name }}</span>
        <span :class="['svc-st', svc.healthy ? 'ok' : 'err']">{{ svc.healthy ? '●' : '✕' }}</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  grid-column: 1;
  grid-row: 2;
  background: var(--bg-panel);
  backdrop-filter: var(--glass);
  -webkit-backdrop-filter: var(--glass);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
  border-right: var(--glass-border);
}
h3 {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 3px;
  color: var(--text-dim);
  padding: 18px 16px 10px;
  font-weight: 700;
  position: relative;
}
h3::after {
  content: '';
  display: block;
  width: 24px;
  height: 2px;
  background: var(--gradient-accent);
  border-radius: 1px;
  margin-top: 8px;
}
.agent-card {
  margin: 4px 10px;
  padding: 12px 12px 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--bg-card);
  backdrop-filter: blur(4px);
  border: 1px solid var(--border);
  border-left: 3px solid transparent;
  cursor: pointer;
  transition: all .25s cubic-bezier(.4, 0, .2, 1);
  position: relative;
  overflow: hidden;
}
.agent-card::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, transparent, rgba(0, 212, 255, .03));
  opacity: 0;
  transition: opacity .25s;
}
.agent-card:hover {
  border-left-color: var(--accent);
  border-color: rgba(0, 212, 255, .2);
  box-shadow: var(--glow);
  transform: translateX(2px);
}
.agent-card:hover::before {
  opacity: 1;
}
.agent-card.active {
  border-left-color: var(--accent);
  border-color: rgba(0, 212, 255, .3);
  background: rgba(0, 212, 255, .06);
  box-shadow: 0 0 20px rgba(0, 212, 255, .15);
}
.name {
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}
.emoji {
  font-size: 16px;
}
.caps {
  font-size: 10px;
  color: var(--text-dim);
  margin-top: 6px;
  line-height: 1.6;
}
.new-conv-btn {
  flex: 1;
  padding: 5px;
  border-radius: 6px;
  border: 1px solid rgba(0, 212, 255, .2);
  background: rgba(0, 212, 255, .06);
  color: #00d4ff;
  font-size: 10px;
  cursor: pointer;
  transition: all .2s;
}
.new-conv-btn:hover {
  background: rgba(0, 212, 255, .12);
  border-color: rgba(0, 212, 255, .4);
}
.conv-list {
  padding: 0 8px 8px;
  max-height: 140px;
  overflow-y: auto;
  font-size: 11px;
}
.conv-list::-webkit-scrollbar { width: 3px; }
.conv-list::-webkit-scrollbar-thumb { background: rgba(0, 212, 255, .2); border-radius: 2px; }
.conv-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border-radius: 6px;
  margin-bottom: 2px;
  cursor: pointer;
  transition: background .15s;
  border: 1px solid transparent;
}
.conv-item:hover { background: rgba(0, 212, 255, .08); }
.conv-item.active {
  background: rgba(0, 212, 255, .12);
  border: 1px solid rgba(0, 212, 255, .2);
}
.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #94a3b8;
}
.conv-item.active .conv-title { color: #00d4ff; }
.conv-del {
  color: #667;
  cursor: pointer;
  font-size: 12px;
  padding: 0 2px;
}
.conv-del:hover { color: #ef4444; }
.sys-info {
  padding: 0 12px 12px;
  font-size: 11px;
  color: var(--text-dim);
  font-family: 'JetBrains Mono', monospace;
  line-height: 1.8;
}
.val-green { color: var(--accent3); }
.val-cyan { color: var(--accent); }
.val-purple { color: var(--accent2); }
.svc-list {
  padding: 0 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.svc-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 6px;
  font-size: 11px;
}
.svc-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.svc-name {
  flex: 1;
  color: var(--text-dim);
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
}
.svc-st { font-size: 10px; }
.svc-st.ok { color: #10b981; }
.svc-st.err { color: #ef4444; }
</style>
