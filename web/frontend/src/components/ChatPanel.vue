<script setup lang="ts">
import { ref, nextTick, watch, computed } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useSSE } from '@/composables/useSSE'

const chatStore = useChatStore()
const { send } = useSSE()
const inputText = ref('')
const messagesEl = ref<HTMLDivElement>()
const showExportMenu = ref(false)
const pendingImage = ref<{ url: string; filename: string } | null>(null)
const lightboxUrl = ref<string | null>(null)
const imgUploading = ref(false)
const videoUploading = ref(false)

function handleSend() {
  if ((!inputText.value.trim() && !pendingImage.value) || chatStore.isStreaming) return
  let msg = inputText.value.trim()
  if (pendingImage.value) {
    msg = `[img:${pendingImage.value.filename}] ${msg}`.trim()
    pendingImage.value = null
  }
  send(msg)
  inputText.value = ''
  nextTick(scrollToBottom)
}

watch(() => chatStore.pendingDrawMessage, (msg) => {
  if (msg && !chatStore.isStreaming) {
    inputText.value = msg
    handleSend()
    chatStore.pendingDrawMessage = ''
  }
})

async function handleImageSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return
  const file = input.files[0]
  input.value = ''
  if (!file.type.startsWith('image/')) {
    chatStore.addBotMessage('⚠️ 请选择图片文件')
    return
  }
  imgUploading.value = true
  const previewUrl = URL.createObjectURL(file)
  try {
    const fd = new FormData()
    fd.append('file', file)
    const resp = await fetch('/api/upload_image', { method: 'POST', body: fd })
    const data = await resp.json()
    if (data.error) {
      chatStore.addBotMessage(`⚠️ 上传失败: ${data.error}`)
      URL.revokeObjectURL(previewUrl)
    } else {
      pendingImage.value = { url: previewUrl, filename: data.filename }
    }
  } catch {
    chatStore.addBotMessage('⚠️ 图片上传失败，请确保后端已启动')
    URL.revokeObjectURL(previewUrl)
  } finally {
    imgUploading.value = false
  }
}

function removePendingImage() {
  if (pendingImage.value) {
    URL.revokeObjectURL(pendingImage.value.url)
    pendingImage.value = null
  }
}

function quickImageAction(action: string) {
  if (!pendingImage.value || chatStore.isStreaming) return
  const prompts: Record<string, string> = {
    disaster: '评估这张灾情照片的淹没情况和损失',
    reconstruct: '重建这个建筑的3D模型',
    analyze: '分析这张图片的内容',
  }
  inputText.value = prompts[action] || ''
  handleSend()
}

async function handleVideoSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return
  const file = input.files[0]
  input.value = ''
  if (!file.type.startsWith('video/')) {
    chatStore.addBotMessage('⚠️ 请选择视频文件')
    return
  }
  videoUploading.value = true
  chatStore.addBotMessage(`📹 正在上传视频: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)}MB)`)
  try {
    const fd = new FormData()
    fd.append('file', file)
    const resp = await fetch('/api/upload_video', { method: 'POST', body: fd })
    const data = await resp.json()
    if (data.error) {
      chatStore.addBotMessage(`⚠️ 上传失败: ${data.error}`)
      return
    }
    chatStore.videoAnalysis = { active: true, filename: data.filename, duration: 0, frames: [], maxWaterRatio: 0, trend: '', trendDelta: 0, glmvAssessment: null, summary: '' }
    chatStore.isStreaming = true

    const ctx = inputText.value.trim()
    const url = `/api/analyze_video?filename=${encodeURIComponent(data.filename)}&context=${encodeURIComponent(ctx)}`
    const es = new EventSource(url)
    es.onmessage = (ev) => {
      let d: any
      try { d = JSON.parse(ev.data) } catch { return }
      const va = chatStore.videoAnalysis
      if (!va) return

      switch (d.type) {
        case 'video_info':
          va.duration = d.duration_s
          break
        case 'video_frame_result':
          va.frames.push({ timestamp: d.timestamp, waterRatio: d.water_ratio, waterChanged: d.water_changed, frameB64: d.frame_b64 })
          break
        case 'video_stats':
          va.maxWaterRatio = d.max_water_ratio
          va.trend = d.trend
          va.trendDelta = d.trend_delta
          break
        case 'video_glmv':
          va.glmvAssessment = d.assessment
          break
        case 'video_analysis_done':
          va.duration = d.duration_s
          va.summary = d.glmv_summary
          va.active = false
          chatStore.isStreaming = false
          es.close()
          break
        case 'video_analysis_error':
          chatStore.addBotMessage(`⚠️ 视频分析失败: ${d.error}`)
          chatStore.isStreaming = false
          es.close()
          break
      }
    }
    es.onerror = () => {
      es.close()
      if (chatStore.videoAnalysis) chatStore.videoAnalysis.active = false
      chatStore.isStreaming = false
    }
  } catch {
    chatStore.addBotMessage('⚠️ 视频上传失败，请确保后端已启动')
  } finally {
    videoUploading.value = false
  }
}

function scrollToBottom() {
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

watch(() => chatStore.messages.length, () => nextTick(scrollToBottom))
watch(() => chatStore.thinkingLines.length, () => nextTick(scrollToBottom))

function toolSummary(result: any) {
  if (!result || typeof result !== 'object') return ''
  const parts: string[] = []
  if (result.geojson) parts.push('GeoJSON')
  if (result.points) parts.push(`${result.points.length}点`)
  if (result.data_points) parts.push('曲线')
  if (result.table) parts.push('表格')
  if (result.image_base64) parts.push('图片')
  return parts.length ? parts.join(' + ') : Object.keys(result).filter(k => !k.startsWith('_')).slice(0, 3).join(', ')
}

function askSuggestion(text: string) {
  if (chatStore.isStreaming) return
  inputText.value = text
  nextTick(() => {
    const input = document.querySelector('input[placeholder*="水利"]') as HTMLInputElement
    if (input) {
      input.focus()
      const xxIdx = text.indexOf('XX')
      if (xxIdx >= 0) {
        input.setSelectionRange(xxIdx, xxIdx + 2)
      } else {
        input.select()
      }
    }
  })
}

function formatMetricVal(v: number): string {
  if (!v && v !== 0) return '—'
  if (v >= 10000) return (v / 10000).toFixed(1) + '万'
  if (Number.isInteger(v)) return v.toString()
  return v.toFixed(2)
}

function isMaxInRow(metric: any, val: number): boolean {
  const vals = metric.values.map((v: any) => v.value)
  return val > 0 && val === Math.max(...vals)
}

function sevColor(sev: number): string {
  return ['', '#22c55e', '#eab308', '#f97316', '#ef4444', '#dc2626'][sev] || '#64748b'
}

function fmtDepth(val: any): string {
  if (val == null) return '—'
  if (typeof val === 'number') return val + 'm'
  if (typeof val === 'string') return /\d/.test(val) ? val + (val.includes('m') ? '' : 'm') : val
  if (typeof val === 'object') {
    if (val.average != null) return `${val.average}m`
    if (val.maximum != null && val.minimum != null) return `${val.minimum}-${val.maximum}m`
    if (val.maximum != null) return `${val.maximum}m`
    const vals = Object.values(val).filter((v: any) => typeof v === 'number')
    if (vals.length) return `${Math.max(...vals)}m`
  }
  return String(val)
}

function fmtBasis(val: any): string {
  if (val == null) return ''
  if (typeof val === 'string') return val
  if (Array.isArray(val)) return val.join('、')
  if (typeof val === 'object') {
    return Object.entries(val).map(([k, v]) => `${k}: ${v}`).join('；')
  }
  return String(val)
}

function fmtPop(val: any): string {
  if (val == null) return '—'
  if (typeof val === 'number') return val > 10000 ? (val / 10000).toFixed(1) + '万' : String(val)
  if (typeof val === 'string') return val
  return String(val)
}

function uploadFile(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return
  const file = input.files[0]
  chatStore.addBotMessage(`📎 已选择文件: ${file.name} (${(file.size / 1024).toFixed(1)}KB)`)
  input.value = ''
}

function extractGeoJSON(result: any) {
  if (!result) return null
  return result.geojson
    || (result.coordinates ? { type: 'Feature', geometry: { type: result.geometry_type || 'Polygon', coordinates: result.coordinates }, properties: { name: chatStore.lastExportData.tool } } : null)
    || result.boundary_geojson
    || result.stream_geojson
    || result.contour_geojson
    || null
}

function exportGeoJSON() {
  const { result, tool } = chatStore.lastExportData
  if (!result) return alert('暂无可导出的数据')
  const gj = extractGeoJSON(result)
  if (!gj) return alert('当前结果不包含GeoJSON数据')
  const blob = new Blob([JSON.stringify(gj, null, 2)], { type: 'application/geo+json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `${tool}_${new Date().toISOString().slice(0, 10)}.geojson`
  a.click()
  URL.revokeObjectURL(a.href)
  showExportMenu.value = false
}

function exportAllGeoJSON() {
  const all = chatStore.allExportData
  if (!all.length) return alert('暂无可导出的数据')
  const fc: any = { type: 'FeatureCollection', features: [] }
  all.forEach(d => {
    const gj = extractGeoJSON(d.result)
    if (!gj) return
    if (gj.type === 'FeatureCollection') gj.features.forEach((f: any) => { f.properties = f.properties || {}; f.properties.source = d.tool; fc.features.push(f) })
    else if (gj.type === 'Feature') { gj.properties = gj.properties || {}; gj.properties.source = d.tool; fc.features.push(gj) }
    else fc.features.push({ type: 'Feature', geometry: gj, properties: { source: d.tool } })
  })
  if (!fc.features.length) return alert('当前结果不包含GeoJSON数据')
  const blob = new Blob([JSON.stringify(fc, null, 2)], { type: 'application/geo+json' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `S-AI_All_${new Date().toISOString().slice(0, 10)}.geojson`
  a.click()
  URL.revokeObjectURL(a.href)
  showExportMenu.value = false
}

function exportReport() {
  const msgs = chatStore.messages
  if (!msgs.length) return alert('暂无可导出的内容')
  let html = '<!DOCTYPE html><html><head><meta charset="utf-8"><title>S-AI 分析报告</title>' +
    '<style>body{font-family:"Microsoft YaHei",sans-serif;max-width:900px;margin:0 auto;padding:40px 20px;color:#333;background:#fff}' +
    'h1{color:#1a1a2e;border-bottom:2px solid #00d4ff;padding-bottom:8px}' +
    '.msg{margin:12px 0;padding:12px 16px;border-radius:8px}' +
    '.msg.user{background:#f0f7ff;border-left:3px solid #0066cc}' +
    '.msg.bot{background:#f8f8f8;border-left:3px solid #00cc88}' +
    '.meta{font-size:11px;color:#999;margin-bottom:4px}' +
    '.footer{text-align:center;color:#999;font-size:11px;margin-top:30px;border-top:1px solid #eee;padding-top:10px}' +
    '</style></head><body>'
  html += '<h1>S-AI 空间智能分析报告</h1>'
  html += `<p style="color:#666;font-size:12px">生成时间: ${new Date().toLocaleString('zh-CN')}</p>`
  msgs.forEach(m => {
    const cls = m.role === 'user' ? 'user' : 'bot'
    let txt = m.content || ''
    if (txt.length > 2000) txt = txt.slice(0, 2000) + '...'
    html += `<div class="msg ${cls}"><div class="meta">${cls === 'user' ? '👤 用户' : '🤖 S-AI'}</div><div>${txt.replace(/</g, '&lt;')}</div></div>`
  })
  html += '<div class="footer">S-AI 空间智能平台 | LUOBIN-PI Research Lab</div></body></html>'
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `S-AI_Report_${new Date().toISOString().slice(0, 10)}.html`
  a.click()
  URL.revokeObjectURL(a.href)
  showExportMenu.value = false
}

function autoPipeline() {
  if (chatStore.isStreaming) return
  const steps = ['DEM坡度分析', '提取河网', '流域提取', '渲染地形到地图']
  let i = 0
  function next() {
    if (i >= steps.length) return
    send(steps[i])
    i++
    setTimeout(next, 25000)
  }
  next()
}

const suggestions = [
  '查询曼宁糙率', '北京设计暴雨', 'SCS-CN径流计算', 'SWMM排水模型',
  '内涝风险评估', '淹没范围图', '排水能力校核', '洪水预警',
  'DEM坡度分析', '流域提取',
]

const hasAnalysisData = computed(() => {
  return chatStore.allExportData.length > 0
    || chatStore.disasterAssessment
    || chatStore.videoAnalysis
    || chatStore.comparisonResult
})

async function generateReport() {
  if (chatStore.isStreaming) return
  const lastUser = [...chatStore.messages].reverse().find(m => m.role === 'user')
  const body = {
    tool_results: chatStore.allExportData,
    disaster_assessment: chatStore.disasterAssessment,
    video_analysis: chatStore.videoAnalysis ? {
      duration: chatStore.videoAnalysis.duration,
      frame_count: chatStore.videoAnalysis.frames.length,
      max_water_ratio: chatStore.videoAnalysis.maxWaterRatio,
      trend: chatStore.videoAnalysis.trend,
    } : null,
    comparison: chatStore.comparisonResult,
    user_query: lastUser?.content || '',
  }
  try {
    const resp = await fetch('/api/generate_report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const html = await resp.text()
    const w = window.open('', '_blank')
    if (w) {
      w.document.write(html)
      w.document.close()
    } else {
      chatStore.addBotMessage('⚠️ 请允许弹出窗口以预览报告')
    }
  } catch {
    chatStore.addBotMessage('⚠️ 报告生成失败，请确保后端已启动')
  }
}

function closeExportMenu(e: MouseEvent) {
  if (showExportMenu.value && !(e.target as HTMLElement).closest('.export-wrap')) {
    showExportMenu.value = false
  }
}
</script>

<template>
  <aside class="chat-panel" @click="closeExportMenu">
    <div class="chat-header">
      <div class="online" />
      S-AI 对话终端
    </div>

    <div class="chat-messages" ref="messagesEl">
      <div v-if="chatStore.messages.length === 0 && chatStore.thinkingLines.length === 0" class="msg bot welcome-msg">
        <div class="avatar bot-av">
          <svg viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"/>
            <circle cx="9" cy="10" r="1.5" fill="#00d4ff"/>
            <circle cx="15" cy="10" r="1.5" fill="#00d4ff"/>
            <path d="M8 15c1.5 1.5 5 1.5 8 0" stroke-linecap="round"/>
            <path d="M3 6V3h3M18 3h3v3" stroke-linecap="round" stroke-width="1"/>
            <circle cx="12" cy="3" r="1" fill="#7c3aed"/>
          </svg>
        </div>
        <div class="msg-content">
          🌊 <b>水利空间智能体已就绪</b><br/><br/>
          我可以帮你进行空间分析、查询水利参数、检索知识库。试试：<br/><br/>
          • 查询HDPE管的曼宁糙率<br/>
          • 北京的暴雨强度公式<br/>
          • 生成一个缓冲区分析<br/>
          • 渲染地图
        </div>
      </div>

      <template v-for="msg in chatStore.messages" :key="msg.id">
        <div :class="['msg', msg.role]">
          <div v-if="msg.role === 'user'" class="avatar user-av">U</div>
          <div v-else class="avatar bot-av">
            <svg viewBox="0 0 24 24" fill="none" stroke="#00d4ff" stroke-width="1.5">
              <circle cx="12" cy="12" r="10"/>
              <circle cx="9" cy="10" r="1.5" fill="#00d4ff"/>
              <circle cx="15" cy="10" r="1.5" fill="#00d4ff"/>
              <path d="M8 15c1.5 1.5 5 1.5 8 0" stroke-linecap="round"/>
            </svg>
          </div>
          <div class="msg-content">{{ msg.content }}</div>
        </div>
      </template>

      <div v-if="chatStore.thinkingHeader.active || chatStore.thinkingLines.length > 0" class="thinking-box">
        <div class="th-header">
          <span v-if="chatStore.thinkingHeader.active" class="th-spinner" />
          <span v-else class="th-check">✓</span>
          {{ chatStore.thinkingHeader.label }} — {{ chatStore.thinkingHeader.agent }}
          <span v-if="chatStore.thinkingHeader.done" class="th-complete">— complete</span>
        </div>
        <div class="th-progress"><div class="th-progress-bar" :style="{ width: Math.min(100, chatStore.thinkingLines.length * 15) + '%' }" /></div>
        <div
          v-for="(line, i) in chatStore.thinkingLines"
          :key="'th_'+i"
          :class="['th-line', line.type, { done: line.done, active: !line.done }]"
        >{{ line.content }}</div>
      </div>

      <div v-for="(ts, i) in chatStore.toolStatuses" :key="'ts_'+i" :class="['tool-status', 'ts-' + ts.status]">
        <span class="ts-icon">{{ ts.status === 'running' ? '⏳' : ts.status === 'error' ? '❌' : '✅' }}</span>
        <span class="ts-name">{{ ts.server }}.{{ ts.tool }}</span>
        <span class="ts-time">{{ ts.status === 'running' ? (Date.now() - ts.startTime) + 'ms' : ts.ms + 'ms' }}</span>
      </div>

      <div v-for="(d, i) in chatStore.dividers" :key="'div_'+i" class="divider-line">{{ d }}</div>

      <div v-for="(tr, i) in chatStore.toolResults" :key="'tool_'+i" class="tool-badge">
        {{ tr.server }}.{{ tr.tool }} {{ tr.elapsed_ms }}ms
        <span v-if="tr.result && !tr.result.error" class="tool-ok">{{ toolSummary(tr.result) }}</span>
        <span v-if="tr.result?.error" class="tool-err">{{ tr.result.error.slice(0, 80) }}</span>
      </div>

      <div v-if="chatStore.chainSuggestions.length > 0" class="chain-suggestion">
        <span class="chain-label">🔗 推荐下一步: </span>
        <button
          v-for="(s, si) in chatStore.chainSuggestions" :key="'cs_'+si"
          class="chain-btn"
          @click="askSuggestion(s.label)"
        >{{ s.label }}</button>
      </div>

      <div v-if="chatStore.toolHtmlParts.length > 0" class="tool-render">
        <div v-for="(html, i) in chatStore.toolHtmlParts" :key="'thtml_'+i" v-html="html" />
      </div>
    </div>

    <div v-if="chatStore.pipelineSteps.length > 0" class="pipeline-dag">
      <div class="pd-header">
        <span>{{ chatStore.pipelineName }}</span>
        <span class="pd-pct">{{ Math.round((chatStore.pipelineSteps.filter(s => s.status === 'done').length + chatStore.pipelineSteps.filter(s => s.status === 'running').length * 0.5) / chatStore.pipelineSteps.length * 100) }}%</span>
      </div>
      <div class="pd-bar-track">
        <div class="pd-bar-fill" :style="{ width: (chatStore.pipelineSteps.filter(s => s.status === 'done').length + chatStore.pipelineSteps.filter(s => s.status === 'running').length * 0.5) / chatStore.pipelineSteps.length * 100 + '%' }"></div>
      </div>
      <div class="pd-nodes">
        <template v-for="(step, si) in chatStore.pipelineSteps" :key="'pl_'+si">
          <div :class="['pd-node', step.status]">
            <span class="pd-icon">{{ step.icon }}</span>
            <span class="pd-label">{{ step.label }}</span>
            <span class="pd-status">{{
              step.status === 'done' ? '✅' : step.status === 'running' ? '🔄' : step.status === 'error' ? '❌' : '⏳'
            }}</span>
          </div>
          <span v-if="si < chatStore.pipelineSteps.length - 1" class="pd-arrow">→</span>
        </template>
      </div>
    </div>

    <div v-if="chatStore.scenarios.length > 0" class="multi-scenario">
      <div class="ms-header">
        <span class="ms-icon">{{ chatStore.multiScenarioIcon || '📊' }}</span>
        <span class="ms-name">{{ chatStore.multiScenarioName }}</span>
        <span class="ms-badge">{{ chatStore.scenarios.length }}情景对比</span>
      </div>
      <div class="ms-cards">
        <div v-for="sc in chatStore.scenarios" :key="'sc_'+sc.id" class="ms-card" :class="{ active: sc.steps.some(s => s.status === 'running') }">
          <div class="msc-label" :class="{ done: sc.steps.every(s => s.status === 'done') }">{{ sc.label }}</div>
          <div class="msc-nodes">
            <template v-for="(step, si) in sc.steps" :key="'ms_'+sc.id+'_'+si">
              <div :class="['msc-node', step.status]">
                <span class="msc-node-icon">{{ step.icon }}</span>
                <span class="msc-node-st">{{
                  step.status === 'done' ? '✅' : step.status === 'running' ? '🔄' : step.status === 'error' ? '❌' : '⏳'
                }}</span>
              </div>
              <span v-if="si < sc.steps.length - 1" class="msc-arrow">→</span>
            </template>
          </div>
        </div>
      </div>
      <div v-if="chatStore.comparisonResult" class="ms-comparison">
        <div class="msc-table-title">📊 {{ chatStore.comparisonResult.summary }}</div>
        <div class="msc-table-wrap">
          <table class="msc-table">
            <thead>
              <tr>
                <th>指标</th>
                <th v-for="sc in chatStore.scenarios" :key="'ct_'+sc.id">{{ sc.label }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(metric, mi) in chatStore.comparisonResult.metrics" :key="metric.key">
                <td class="msc-metric-name">{{ metric.metric }}</td>
                <td v-for="v in metric.values" :key="v.scenario_id" :class="{ 'msc-max': isMaxInRow(metric, v.value) }">
                  {{ formatMetricVal(v.value) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="chatStore.disasterAssessment" class="disaster-card" :class="'sev-' + (chatStore.disasterAssessment.severity || 1)">
      <div class="dc-header">
        <span class="dc-icon">🚨</span>
        <span class="dc-title">灾情智能评估</span>
        <span class="dc-sev-badge">{{ chatStore.disasterAssessment.severity || '?' }}级</span>
      </div>
      <div class="dc-body">
        <div v-if="chatStore.disasterAssessment.image_url" class="dc-image" @click="lightboxUrl = chatStore.disasterAssessment.image_url">
          <img :src="chatStore.disasterAssessment.image_url" />
          <div class="dc-image-overlay">🔍 点击放大</div>
        </div>
        <div class="dc-row">
          <div class="dc-cell">
            <div class="dc-cell-label">灾害类型</div>
            <div class="dc-cell-val">{{ chatStore.disasterAssessment.disaster_type || '—' }}</div>
          </div>
          <div class="dc-cell">
            <div class="dc-cell-label">估算水深</div>
            <div class="dc-cell-val">{{ fmtDepth(chatStore.disasterAssessment.water_depth_m) }}</div>
          </div>
          <div class="dc-cell">
            <div class="dc-cell-label">受影响人口</div>
            <div class="dc-cell-val">{{ fmtPop(chatStore.disasterAssessment.estimated_affected_population) }}</div>
          </div>
        </div>

        <div v-if="chatStore.disasterAssessment.depth_basis" class="dc-detail">
          <span class="dc-detail-label">📏 水深依据：</span>{{ fmtBasis(chatStore.disasterAssessment.depth_basis) }}
        </div>

        <div v-if="chatStore.disasterAssessment.affected_buildings?.length" class="dc-section">
          <div class="dc-section-title">🏚️ 受损建筑</div>
          <div class="dc-tags">
            <span v-for="(b, bi) in chatStore.disasterAssessment.affected_buildings" :key="'bld_'+bi" class="dc-tag">
              {{ b.type }} ×{{ b.count }} <small>{{ b.status }}</small>
            </span>
          </div>
        </div>

        <div v-if="chatStore.disasterAssessment.affected_roads" class="dc-detail">
          <span class="dc-detail-label">🛣️ 道路设施：</span>{{ chatStore.disasterAssessment.affected_roads }}
        </div>

        <div v-if="chatStore.disasterAssessment.hazards?.length" class="dc-section">
          <div class="dc-section-title">⚠️ 安全隐患</div>
          <div class="dc-tags">
            <span v-for="(h, hi) in chatStore.disasterAssessment.hazards" :key="'hz_'+hi" class="dc-tag dc-tag-warn">{{ h }}</span>
          </div>
        </div>

        <div v-if="chatStore.disasterAssessment.recommended_actions?.length" class="dc-section">
          <div class="dc-section-title">📋 建议措施</div>
          <div class="dc-actions">
            <div v-for="(a, ai) in chatStore.disasterAssessment.recommended_actions" :key="'act_'+ai" class="dc-action">
              <span class="dc-action-num">{{ ai + 1 }}</span>{{ a }}
            </div>
          </div>
        </div>

        <div class="dc-footer">
          <span class="dc-conf">置信度 {{ ((chatStore.disasterAssessment.confidence || 0) * 100).toFixed(0) }}%</span>
          <span class="dc-summary">{{ chatStore.disasterAssessment.summary || '' }}</span>
        </div>
      </div>
    </div>

    <div v-if="chatStore.videoAnalysis" class="video-analysis-card">
      <div class="va-header">
        <span class="va-icon">📹</span>
        <span class="va-title">水务视频分析</span>
        <span v-if="chatStore.videoAnalysis.trend" class="va-trend-badge" :class="chatStore.videoAnalysis.trend">
          {{ chatStore.videoAnalysis.trend === 'rising' ? '📈 水位上涨' : chatStore.videoAnalysis.trend === 'falling' ? '📉 水位下降' : '➡️ 水体稳定' }}
        </span>
      </div>
      <div class="va-body">
        <div class="va-stats">
          <div class="va-stat"><span class="va-stat-label">视频时长</span><span class="va-stat-val">{{ chatStore.videoAnalysis.duration }}s</span></div>
          <div class="va-stat"><span class="va-stat-label">分析帧数</span><span class="va-stat-val">{{ chatStore.videoAnalysis.frames.length }}</span></div>
          <div class="va-stat"><span class="va-stat-label">最大水面占比</span><span class="va-stat-val">{{ (chatStore.videoAnalysis.maxWaterRatio * 100).toFixed(1) }}%</span></div>
        </div>
        <div v-if="chatStore.videoAnalysis.frames.length" class="va-frames">
          <div v-for="(f, fi) in chatStore.videoAnalysis.frames" :key="'vf_'+fi" class="va-frame" @click="lightboxUrl = 'data:image/jpeg;base64,' + f.frameB64">
            <img :src="'data:image/jpeg;base64,' + f.frameB64" />
            <div class="va-frame-info">
              <span>{{ f.timestamp }}s</span>
              <span :class="{ rising: f.waterChanged > 0.01, falling: f.waterChanged < -0.01 }">{{ (f.waterRatio * 100).toFixed(1) }}%</span>
            </div>
          </div>
        </div>
        <div v-if="chatStore.videoAnalysis.glmvAssessment" class="va-glmv">
          <div class="va-glmv-title">🧠 AI场景分析</div>
          <div class="va-glmv-body">
            <span v-if="chatStore.videoAnalysis.glmvAssessment.water_type">类型: {{ chatStore.videoAnalysis.glmvAssessment.water_type }}</span>
            <span v-if="chatStore.videoAnalysis.glmvAssessment.water_state">状态: {{ chatStore.videoAnalysis.glmvAssessment.water_state }}</span>
            <span v-if="chatStore.videoAnalysis.glmvAssessment.risk_level">风险: {{ chatStore.videoAnalysis.glmvAssessment.risk_level }}级</span>
          </div>
          <div v-if="chatStore.videoAnalysis.summary" class="va-glmv-summary">{{ chatStore.videoAnalysis.summary }}</div>
        </div>
      </div>
    </div>

    <div class="suggestions">
      <span
        v-for="s in suggestions" :key="s"
        class="suggestion"
        @click="askSuggestion(s)"
      >{{ s }}</span>
      <span class="suggestion auto-pipeline" @click="autoPipeline">auto-pipeline</span>
      <span v-if="hasAnalysisData" class="suggestion gen-report" @click="generateReport">📋 生成报告</span>
    </div>

    <div v-if="pendingImage || imgUploading" class="img-preview-bar">
      <div v-if="imgUploading" class="img-uploading">
        <span class="img-spin"></span> 上传中...
      </div>
      <template v-else-if="pendingImage">
        <div class="img-thumb-wrap" @click="lightboxUrl = pendingImage!.url">
          <img :src="pendingImage!.url" class="img-thumb" />
          <div class="img-thumb-overlay">🔍 点击放大</div>
        </div>
        <span class="img-name">{{ pendingImage!.filename }}</span>
        <button class="img-quick img-quick-disaster" @click="quickImageAction('disaster')">🚨 灾情评估</button>
        <button class="img-quick" @click="quickImageAction('reconstruct')">🏗️ 3D重建</button>
        <button class="img-quick" @click="quickImageAction('analyze')">🔍 通用分析</button>
        <button class="img-remove" @click="removePendingImage">✕</button>
      </template>
    </div>

    <div class="chat-input">
      <label class="input-btn" title="上传GIS数据">
        📎
        <input type="file" accept=".geojson,.json,.shp,.zip,.gpkg,.kml,.csv" style="display:none" @change="uploadFile" />
      </label>
      <label class="input-btn" :class="{ active: !!pendingImage }" title="上传图片">
        {{ imgUploading ? '⏳' : '📷' }}
        <input type="file" accept="image/*" style="display:none" @change="handleImageSelect" :disabled="imgUploading" />
      </label>
      <label class="input-btn" :class="{ active: videoUploading }" title="上传视频分析">
        {{ videoUploading ? '⏳' : '📹' }}
        <input type="file" accept="video/*" style="display:none" @change="handleVideoSelect" :disabled="videoUploading" />
      </label>
      <input
        v-model="inputText"
        type="text"
        placeholder="输入水利分析指令..."
        @keydown.enter="handleSend"
        :disabled="chatStore.isStreaming"
      />
      <button @click="handleSend" :disabled="chatStore.isStreaming" class="send-btn">➤</button>
      <div class="export-wrap" style="position:relative;display:inline-block">
        <button class="input-btn" @click.stop="showExportMenu = !showExportMenu" title="导出">💾</button>
        <div v-if="showExportMenu" class="export-menu">
          <button @click="exportGeoJSON">📄 导出当前GeoJSON</button>
          <button @click="exportAllGeoJSON">🗺️ 导出全部GeoJSON</button>
          <button @click="exportReport">📊 导出分析报告</button>
        </div>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="lightboxUrl" class="lightbox" @click="lightboxUrl = null">
        <img :src="lightboxUrl" class="lightbox-img" />
        <button class="lightbox-close" @click.stop="lightboxUrl = null">✕</button>
      </div>
    </Teleport>
  </aside>
</template>

<style scoped>
.chat-panel {
  grid-column: 3;
  grid-row: 2;
  background: var(--bg-panel);
  backdrop-filter: var(--glass);
  -webkit-backdrop-filter: var(--glass);
  display: flex;
  flex-direction: column;
  border-left: var(--glass-border);
  overflow: hidden;
  min-height: 0;
}
.chat-header {
  padding: 14px 20px;
  border-bottom: var(--glass-border);
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 14px;
  flex-shrink: 0;
  background: rgba(13, 19, 33, .5);
}
.online {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent3);
  box-shadow: 0 0 8px var(--accent3);
  animation: pulse 2s infinite;
}
.chat-messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  scroll-behavior: smooth;
}
.chat-messages::-webkit-scrollbar { width: 5px; }
.chat-messages::-webkit-scrollbar-track { background: transparent; }
.chat-messages::-webkit-scrollbar-thumb { background: rgba(0, 212, 255, .2); border-radius: 3px; }
.chat-messages::-webkit-scrollbar-thumb:hover { background: rgba(0, 212, 255, .35); }
.msg {
  max-width: 88%;
  animation: slideUp .35s cubic-bezier(.4, 0, .2, 1);
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.avatar {
  width: 36px;
  height: 36px;
  min-width: 36px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  font-size: 16px;
  font-weight: 700;
  flex-shrink: 0;
  position: relative;
  overflow: hidden;
}
.avatar::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  border: 1px solid rgba(255, 255, 255, .1);
}
.bot-av {
  background: linear-gradient(135deg, #0d1a2d, #0a1628);
  box-shadow: 0 0 16px rgba(0, 212, 255, .2);
}
.bot-av svg { width: 22px; height: 22px; }
.user-av {
  background: linear-gradient(135deg, rgba(0, 212, 255, .15), rgba(124, 58, 237, .15));
  box-shadow: 0 0 16px rgba(124, 58, 237, .2);
  font-size: 14px;
  color: var(--text);
}
.msg.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.msg.user .msg-content {
  background: linear-gradient(135deg, rgba(0, 212, 255, .1), rgba(124, 58, 237, .1));
  border: 1px solid rgba(0, 212, 255, .18);
  border-radius: var(--radius) var(--radius) 4px var(--radius);
  padding: 10px 16px;
  font-size: 13px;
  line-height: 1.6;
  backdrop-filter: blur(4px);
  animation: msgUserIn .4s cubic-bezier(.4, 0, .2, 1);
  position: relative;
  overflow: hidden;
}
.msg.user .msg-content::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: inherit;
  background: linear-gradient(135deg, rgba(0, 212, 255, .08), transparent, rgba(124, 58, 237, .08));
  opacity: 0;
  transition: opacity .3s;
}
.msg.user:hover .msg-content::after { opacity: 1; }
.msg.bot .msg-content {
  background: var(--bg-card);
  backdrop-filter: blur(4px);
  border: 1px solid var(--border);
  border-radius: var(--radius) var(--radius) var(--radius) 4px;
  padding: 12px 16px;
  font-size: 13px;
  line-height: 1.7;
  min-width: 200px;
  word-break: break-word;
  animation: msgBotIn .4s cubic-bezier(.4, 0, .2, 1);
}
.welcome-msg {
  max-width: 95%;
}
.thinking-box {
  width: 100%;
  background: rgba(124, 58, 237, .06);
  border: 1px solid rgba(124, 58, 237, .18);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  line-height: 1.9;
  max-height: 260px;
  overflow-y: auto;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  animation: thinkReveal .35s cubic-bezier(.22, 1, .36, 1);
  position: relative;
}
.thinking-box::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent 0%, #7c3aed 20%, #00d4ff 50%, #7c3aed 80%, transparent 100%);
  background-size: 200% 100%;
  animation: borderSweep 2s linear infinite;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
}
.th-header {
  color: var(--accent2);
  font-weight: 600;
  font-size: 11px;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
  letter-spacing: .5px;
}
.th-spinner {
  display: inline-block;
  width: 10px; height: 10px;
  border: 2px solid rgba(124, 58, 237, .2);
  border-top-color: var(--accent2);
  border-radius: 50%;
  animation: spin .6s linear infinite;
}
.th-check { color: var(--accent3); font-size: 13px; }
.th-complete { color: var(--text-dim); }
.th-progress {
  height: 2px;
  background: rgba(124, 58, 237, .1);
  border-radius: 1px;
  margin-bottom: 6px;
  overflow: hidden;
}
.th-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #7c3aed, #00d4ff);
  border-radius: 1px;
  transition: width .3s ease;
}
.th-line {
  color: var(--text-dim);
  padding: 1px 0 1px 16px;
  position: relative;
  animation: thinkLineIn .3s ease;
  white-space: pre-wrap;
  overflow-wrap: break-word;
  font-size: 11px;
  line-height: 1.5;
}
.th-line::before {
  content: '>';
  position: absolute;
  left: 0;
  color: var(--accent2);
  opacity: .4;
  font-weight: 700;
}
.th-line.active { color: var(--text); text-shadow: 0 0 6px rgba(0, 212, 255, .12); }
.th-line.done { color: var(--accent3); }
.th-line.step-header { color: #00d4ff; font-weight: 600; margin-top: 4px; border-top: 1px solid rgba(0, 212, 255, .1); padding-top: 4px; }
.th-line.step-goal { color: #7c3aed; font-style: italic; }
.th-line.step-decision { color: #ff8800; }
.th-line.step-error { color: #ff4444; }
.th-line.step-ok { color: #00ff88; }
.tool-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  margin: 3px 0;
  animation: slideUp .3s ease;
}
.tool-status.ts-running { background: rgba(0, 212, 255, .06); border: 1px solid rgba(0, 212, 255, .15); color: var(--accent); }
.tool-status.ts-ok { background: rgba(16, 185, 129, .06); border: 1px solid rgba(16, 185, 129, .15); color: var(--accent3); animation: tsFlash .7s ease; }
.tool-status.ts-error { background: rgba(239, 68, 68, .06); border: 1px solid rgba(239, 68, 68, .15); color: var(--danger); }
.ts-icon { font-size: 12px; }
.ts-name { color: var(--text-dim); }
.ts-time { color: var(--text-dim); font-size: 10px; }
.divider-line {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
  font-size: 11px;
  color: var(--accent);
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 1.5px;
  text-shadow: 0 0 8px rgba(0, 212, 255, .3);
}
.divider-line::before, .divider-line::after {
  content: '';
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(0, 212, 255, .4), transparent);
}
.chain-suggestion {
  margin: 6px 0;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid rgba(124, 58, 237, .2);
  background: rgba(124, 58, 237, .06);
  font-size: 11px;
}
.chain-label { color: #c4b5fd; font-weight: 600; }
.chain-btn {
  display: inline-block;
  margin: 2px 4px;
  padding: 3px 10px;
  border-radius: 12px;
  border: 1px solid rgba(124, 58, 237, .3);
  background: rgba(124, 58, 237, .1);
  color: #c4b5fd;
  cursor: pointer;
  font-size: 11px;
  transition: all .2s;
}
.chain-btn:hover {
  background: rgba(124, 58, 237, .25);
  border-color: rgba(124, 58, 237, .5);
}

.pipeline-dag {
  margin: 8px 0;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid rgba(0, 212, 255, .15);
  background: rgba(0, 212, 255, .04);
}
.pd-header {
  font-size: 13px;
  font-weight: 700;
  color: #67e8f9;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.pd-pct {
  font-size: 14px;
  font-weight: 800;
  color: #4ade80;
  font-variant-numeric: tabular-nums;
}
.pd-bar-track {
  height: 4px;
  border-radius: 2px;
  background: rgba(255,255,255,.06);
  overflow: hidden;
  margin-bottom: 10px;
}
.pd-bar-fill {
  height: 100%;
  border-radius: 2px;
  background: linear-gradient(90deg, #22d3ee, #4ade80);
  transition: width .5s ease;
}
.pd-nodes {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-wrap: wrap;
}
.pd-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,.08);
  background: rgba(255,255,255,.03);
  min-width: 72px;
  transition: all .3s;
}
.pd-node.running {
  border-color: rgba(250, 204, 21, .5);
  background: rgba(250, 204, 21, .08);
  box-shadow: 0 0 12px rgba(250, 204, 21, .15);
}
.pd-node.done {
  border-color: rgba(74, 222, 128, .4);
  background: rgba(74, 222, 128, .06);
}
.pd-node.error {
  border-color: rgba(248, 113, 113, .4);
  background: rgba(248, 113, 113, .06);
}
.pd-icon { font-size: 20px; }
.pd-label { font-size: 11px; color: #cbd5e1; }
.pd-status { font-size: 13px; }
.pd-arrow { color: rgba(255,255,255,.2); font-size: 14px; }

.multi-scenario {
  margin: 8px 0;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid rgba(168, 85, 247, .2);
  background: rgba(168, 85, 247, .04);
}
.ms-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  font-size: 13px;
  font-weight: 700;
  color: #c4b5fd;
}
.ms-badge {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(168, 85, 247, .15);
  border: 1px solid rgba(168, 85, 247, .3);
  color: #d8b4fe;
}
.ms-cards {
  display: flex;
  gap: 10px;
  overflow-x: auto;
  padding-bottom: 4px;
}
.ms-card {
  flex: 1;
  min-width: 200px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,.08);
  background: rgba(0,0,0,.2);
  transition: all .3s;
}
.ms-card.active {
  border-color: rgba(250, 204, 21, .4);
  box-shadow: 0 0 12px rgba(250, 204, 21, .1);
}
.msc-label {
  font-size: 12px;
  font-weight: 600;
  color: #a5b4fc;
  margin-bottom: 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid rgba(255,255,255,.06);
}
.msc-label.done { color: #4ade80; }
.msc-nodes {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-wrap: wrap;
}
.msc-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid rgba(255,255,255,.06);
  background: rgba(255,255,255,.02);
  min-width: 36px;
  transition: all .3s;
}
.msc-node.running {
  border-color: rgba(250, 204, 21, .5);
  background: rgba(250, 204, 21, .08);
  animation: pulse 1s infinite;
}
.msc-node.done {
  border-color: rgba(74, 222, 128, .4);
  background: rgba(74, 222, 128, .06);
}
.msc-node.error {
  border-color: rgba(248, 113, 113, .4);
  background: rgba(248, 113, 113, .06);
}
.msc-node-icon { font-size: 16px; }
.msc-node-st { font-size: 11px; }
.msc-arrow { color: rgba(255,255,255,.15); font-size: 12px; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: .6; }
}
.ms-comparison {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(255,255,255,.06);
}
.msc-table-title {
  font-size: 12px;
  font-weight: 600;
  color: #c4b5fd;
  margin-bottom: 8px;
}
.msc-table-wrap { overflow-x: auto; }
.msc-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.msc-table th {
  padding: 6px 10px;
  text-align: center;
  color: #a5b4fc;
  font-weight: 600;
  border-bottom: 1px solid rgba(168, 85, 247, .2);
  white-space: nowrap;
}
.msc-table td {
  padding: 5px 10px;
  text-align: center;
  color: #cbd5e1;
  border-bottom: 1px solid rgba(255,255,255,.04);
}
.msc-table td.msc-metric-name {
  text-align: left;
  color: #94a3b8;
  white-space: nowrap;
}
.msc-table td.msc-max {
  color: #fbbf24;
  font-weight: 700;
}

.disaster-card {
  margin: 8px 0;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(239, 68, 68, .25);
  background: rgba(239, 68, 68, .03);
}
.disaster-card.sev-1 { border-color: rgba(34, 197, 94, .25); background: rgba(34, 197, 94, .03); }
.disaster-card.sev-2 { border-color: rgba(234, 179, 8, .25); background: rgba(234, 179, 8, .03); }
.disaster-card.sev-3 { border-color: rgba(249, 115, 22, .25); background: rgba(249, 115, 22, .03); }
.disaster-card.sev-4 { border-color: rgba(239, 68, 68, .3); background: rgba(239, 68, 68, .05); }
.disaster-card.sev-5 { border-color: rgba(220, 38, 38, .4); background: rgba(220, 38, 38, .08); }
.dc-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(255,255,255,.06);
}
.dc-icon { font-size: 18px; }
.dc-title { font-size: 14px; font-weight: 700; color: #fca5a5; }
.dc-sev-badge {
  margin-left: auto;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 700;
  background: rgba(239, 68, 68, .15);
  color: #fca5a5;
  border: 1px solid rgba(239, 68, 68, .3);
}
.dc-body { padding: 12px 14px; }
.dc-image {
  position: relative;
  margin-bottom: 10px;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  max-height: 200px;
}
.dc-image img {
  width: 100%;
  max-height: 200px;
  object-fit: cover;
  display: block;
}
.dc-image-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 4px 10px;
  background: linear-gradient(transparent, rgba(0,0,0,.7));
  color: #fff;
  font-size: 11px;
  opacity: 0;
  transition: opacity .2s;
}
.dc-image:hover .dc-image-overlay { opacity: 1; }
.dc-row {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
}
.dc-cell {
  flex: 1;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(0,0,0,.25);
  text-align: center;
}
.dc-cell-label { font-size: 10px; color: #94a3b8; margin-bottom: 3px; }
.dc-cell-val { font-size: 16px; font-weight: 700; color: #e2e8f0; }
.dc-detail {
  font-size: 12px;
  color: #cbd5e1;
  margin: 6px 0;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(0,0,0,.15);
}
.dc-detail-label { color: #94a3b8; }
.dc-section { margin: 8px 0; }
.dc-section-title { font-size: 12px; font-weight: 600; color: #fca5a5; margin-bottom: 5px; }
.dc-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.dc-tag {
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 11px;
  background: rgba(255,255,255,.06);
  color: #cbd5e1;
  border: 1px solid rgba(255,255,255,.08);
}
.dc-tag small { color: #f87171; }
.dc-tag-warn {
  background: rgba(239, 68, 68, .1);
  border-color: rgba(239, 68, 68, .2);
  color: #fca5a5;
}
.dc-actions { display: flex; flex-direction: column; gap: 5px; }
.dc-action {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  color: #e2e8f0;
  background: rgba(0,0,0,.15);
}
.dc-action-num {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: rgba(239, 68, 68, .2);
  color: #fca5a5;
  font-size: 10px;
  font-weight: 700;
  flex-shrink: 0;
}
.dc-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid rgba(255,255,255,.06);
  font-size: 11px;
}
.dc-conf { color: #94a3b8; white-space: nowrap; }
.dc-summary { color: #cbd5e1; }

.video-analysis-card {
  margin: 8px 0;
  border-radius: 12px;
  border: 1px solid rgba(0, 212, 255, .2);
  background: rgba(0, 212, 255, .03);
  overflow: hidden;
}
.va-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(255,255,255,.06);
}
.va-icon { font-size: 18px; }
.va-title { font-size: 14px; font-weight: 700; color: #67e8f9; }
.va-trend-badge {
  margin-left: auto;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
}
.va-trend-badge.rising { background: rgba(239,68,68,.15); color: #fca5a5; }
.va-trend-badge.falling { background: rgba(34,197,94,.15); color: #86efac; }
.va-trend-badge.stable { background: rgba(148,163,184,.15); color: #cbd5e1; }
.va-body { padding: 12px 14px; }
.va-stats { display: flex; gap: 10px; margin-bottom: 10px; }
.va-stat {
  flex: 1;
  text-align: center;
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(0,0,0,.25);
}
.va-stat-label { display: block; font-size: 10px; color: #94a3b8; }
.va-stat-val { display: block; font-size: 15px; font-weight: 700; color: #67e8f9; }
.va-frames {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding-bottom: 6px;
}
.va-frame {
  flex-shrink: 0;
  width: 120px;
  border-radius: 6px;
  overflow: hidden;
  cursor: pointer;
  border: 1px solid rgba(255,255,255,.08);
  transition: all .15s;
}
.va-frame:hover { border-color: rgba(0,212,255,.4); }
.va-frame img { width: 100%; height: 68px; object-fit: cover; display: block; }
.va-frame-info {
  display: flex;
  justify-content: space-between;
  padding: 3px 6px;
  font-size: 10px;
  color: #94a3b8;
  background: rgba(0,0,0,.4);
}
.va-frame-info .rising { color: #fca5a5; }
.va-frame-info .falling { color: #86efac; }
.va-glmv {
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(168, 85, 247, .06);
  border: 1px solid rgba(168, 85, 247, .15);
}
.va-glmv-title { font-size: 12px; font-weight: 600; color: #c4b5fd; margin-bottom: 5px; }
.va-glmv-body { display: flex; gap: 12px; font-size: 11px; color: #cbd5e1; flex-wrap: wrap; }
.va-glmv-summary { font-size: 11px; color: #94a3b8; margin-top: 5px; }
.th-line.done { color: var(--accent3); }
.tool-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: rgba(0, 212, 255, .06);
  border: 1px solid rgba(0, 212, 255, .12);
  color: var(--accent);
  font-size: 10px;
  padding: 2px 10px;
  border-radius: 10px;
  font-family: 'JetBrains Mono', monospace;
  margin: 4px 2px;
}
.tool-ok { color: var(--accent3); }
.tool-err { color: var(--danger); }
.tool-render {
  border: 1px solid rgba(0, 212, 255, .15);
  border-radius: var(--radius-sm);
  padding: 10px 14px;
  background: var(--bg-card);
  margin: 6px 0;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
}
.tool-render :deep(.tr-accent) { color: #00d4ff; }
.tool-render :deep(.tr-warn) { color: #ff8800; }
.tool-render :deep(.tr-danger) { color: #ff4444; }
.tool-render :deep(.tr-dim) { color: #8899aa; }
.tool-render :deep(.tr-sub) { font-size: 11px; margin-top: 4px; color: #8899aa; }
.tool-render :deep(.tr-purple) { color: #cc88ff; }
.tool-render :deep(.tr-card) {
  padding: 10px 14px; border-radius: var(--radius-sm);
  background: rgba(124, 58, 237, .07); border: 1px solid rgba(124, 58, 237, .2);
}
.tool-render :deep(.tr-alert) {
  padding: 10px 14px; border-radius: var(--radius-sm);
  background: rgba(255, 68, 68, .07); border: 1px solid rgba(255, 68, 68, .2); color: #ff4444;
}
.tool-render :deep(.tr-alert-text) { font-size: 12px; }
.tool-render :deep(.tr-chart) {
  width: 100%; max-width: 420px; border-radius: 6px; background: #0a0e1a; margin: 4px 0;
}
.tool-render :deep(.tr-table) {
  width: 100%; border-collapse: collapse; font-size: 11px; margin: 4px 0;
}
.tool-render :deep(.tr-table th) {
  text-align: left; padding: 4px 8px; border-bottom: 1px solid #1a2332; color: #667;
}
.tool-render :deep(.tr-table td) {
  padding: 3px 8px; border-bottom: 1px solid #0d1117; color: #aab;
}
.tool-render :deep(.tr-details) { margin: 4px 0; }
.tool-render :deep(.tr-details summary) {
  cursor: pointer; font-size: 11px; color: #667; padding: 4px 0;
}
.tool-render :deep(.tr-recon-card) {
  padding: 12px; border-radius: var(--radius-sm);
  background: rgba(0, 212, 255, .06); border: 1px solid rgba(0, 212, 255, .2);
}
.tool-render :deep(.tr-recon-header) { font-size: 13px; font-weight: 600; color: #00d4ff; margin-bottom: 8px; }
.tool-render :deep(.tr-recon-stats) { display: flex; gap: 12px; margin-bottom: 8px; }
.tool-render :deep(.tr-recon-stat) { text-align: center; }
.tool-render :deep(.tr-recon-num) { display: block; font-size: 16px; font-weight: 700; color: #e2e8f0; }
.tool-render :deep(.tr-recon-lbl) { font-size: 10px; color: #64748b; }
.tool-render :deep(.tr-recon-actions) { display: flex; gap: 6px; }
.tool-render :deep(.tr-recon-btn) {
  font-size: 11px; padding: 5px 12px; border-radius: 6px;
  border: 1px solid var(--border-solid); background: var(--bg-card);
  color: var(--text); cursor: pointer; text-decoration: none;
  display: inline-flex; align-items: center; transition: all .15s;
}
.tool-render :deep(.tr-recon-btn:hover) { border-color: var(--accent); color: var(--accent); }
.tool-render :deep(.tr-recon-btn.primary) {
  border-color: rgba(0, 212, 255, .4); color: #00d4ff;
  background: rgba(0, 212, 255, .08);
}
.tool-render :deep(.tr-code) {
  font-size: 10px; color: #8899aa; background: #080c14;
  padding: 8px; border-radius: 4px; white-space: pre-wrap;
  max-height: 200px; overflow: auto; margin-top: 4px;
}
.tool-render :deep(.tr-json) {
  color: #8899aa; font-size: 11px; white-space: pre-wrap;
  max-height: 200px; overflow: auto;
}
.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 0 14px 10px;
  flex-shrink: 0;
}
.suggestion {
  font-size: 11px;
  padding: 5px 12px;
  border-radius: 20px;
  background: rgba(0, 212, 255, .04);
  border: 1px solid rgba(0, 212, 255, .1);
  color: var(--text-dim);
  cursor: pointer;
  transition: all .25s;
}
.suggestion:hover {
  border-color: rgba(0, 212, 255, .3);
  color: var(--accent);
  background: rgba(0, 212, 255, .08);
  box-shadow: 0 0 8px rgba(0, 212, 255, .1);
}
.chat-input {
  padding: 12px 14px;
  border-top: var(--glass-border);
  display: flex;
  gap: 10px;
  align-items: center;
  flex-shrink: 0;
  background: rgba(13, 19, 33, .5);
  position: relative;
  transition: all .4s ease;
}
.input-btn {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius);
  background: var(--bg-input);
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-size: 18px;
  cursor: pointer;
  transition: border-color .2s;
}
.input-btn:hover { border-color: rgba(0, 212, 255, .4); }
.chat-input input[type="text"] {
  flex: 1;
  background: var(--bg-input);
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 18px;
  color: var(--text-bright);
  font-size: 13px;
  outline: none;
  transition: all .3s cubic-bezier(.4, 0, .2, 1);
}
.chat-input input[type="text"]:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(0, 212, 255, .1), 0 0 16px rgba(0, 212, 255, .1);
}
.chat-input input[type="text"]::placeholder { color: var(--text-dim); }
.chat-input input[type="text"]:disabled { opacity: .5; }
.send-btn {
  width: 44px;
  height: 44px;
  border-radius: var(--radius);
  background: var(--gradient-accent);
  border: none;
  color: white;
  font-size: 18px;
  cursor: pointer;
  display: grid;
  place-items: center;
  box-shadow: 0 2px 12px rgba(0, 212, 255, .25);
  transition: all .2s cubic-bezier(.4, 0, .2, 1);
}
.send-btn:hover:not(:disabled) {
  transform: translateY(-1px) scale(1.04);
  box-shadow: 0 4px 20px rgba(0, 212, 255, .4);
}
.send-btn:active:not(:disabled) { transform: scale(.96); }
.send-btn:disabled { opacity: .5; cursor: not-allowed; }
.suggestion.auto-pipeline {
  border-color: var(--accent2);
  color: var(--accent2);
}
.suggestion.auto-pipeline:hover {
  background: rgba(168, 85, 237, .25);
  border-color: rgba(168, 85, 237, .5);
}
.suggestion.gen-report {
  border-color: rgba(34, 197, 94, .3);
  background: rgba(34, 197, 94, .08);
  color: #4ade80;
  font-weight: 600;
}
.suggestion.gen-report:hover {
  background: rgba(34, 197, 94, .2);
  border-color: rgba(34, 197, 94, .5);
}
.export-menu {
  position: absolute;
  bottom: 48px;
  right: 0;
  background: rgba(13, 19, 33, .95);
  border: 1px solid rgba(0, 212, 255, .2);
  border-radius: 8px;
  padding: 6px 0;
  min-width: 180px;
  z-index: 9999;
  box-shadow: 0 8px 32px rgba(0, 0, 0, .5);
}
.export-menu button {
  display: block;
  width: 100%;
  padding: 8px 14px;
  border: none;
  background: transparent;
  color: #e2e8f0;
  text-align: left;
  font-size: 12px;
  cursor: pointer;
}
.export-menu button:hover {
  background: rgba(0, 212, 255, .1);
}

.img-preview-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  border-top: 1px solid rgba(0, 212, 255, .1);
  background: rgba(0, 212, 255, .03);
  flex-shrink: 0;
}
.img-uploading {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-dim);
}
.img-spin {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(0, 212, 255, .2);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin .6s linear infinite;
}
.img-thumb-wrap {
  position: relative;
  width: 56px;
  height: 56px;
  border-radius: 8px;
  overflow: hidden;
  cursor: pointer;
  border: 2px solid rgba(0, 212, 255, .3);
  flex-shrink: 0;
  transition: border-color .2s;
}
.img-thumb-wrap:hover {
  border-color: var(--accent);
}
.img-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.img-thumb-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, .6);
  color: #fff;
  font-size: 10px;
  opacity: 0;
  transition: opacity .2s;
}
.img-thumb-wrap:hover .img-thumb-overlay {
  opacity: 1;
}
.img-name {
  flex: 1;
  font-size: 11px;
  color: var(--text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.img-remove {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  border: 1px solid rgba(239, 68, 68, .3);
  background: rgba(239, 68, 68, .1);
  color: #ff6b6b;
  cursor: pointer;
  font-size: 12px;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  transition: all .15s;
}
.img-remove:hover {
  background: rgba(239, 68, 68, .25);
  border-color: rgba(239, 68, 68, .5);
}
.img-quick {
  padding: 4px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255,255,255,.1);
  background: rgba(255,255,255,.04);
  color: #cbd5e1;
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
  transition: all .15s;
  flex-shrink: 0;
}
.img-quick:hover {
  background: rgba(0, 212, 255, .12);
  border-color: rgba(0, 212, 255, .3);
  color: #00d4ff;
}
.img-quick-disaster {
  border-color: rgba(239, 68, 68, .3);
  background: rgba(239, 68, 68, .08);
  color: #fca5a5;
  font-weight: 600;
}
.img-quick-disaster:hover {
  background: rgba(239, 68, 68, .2);
  border-color: rgba(239, 68, 68, .5);
  color: #fff;
}
.input-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(0, 212, 255, .08);
}
</style>

<style>
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 99999;
  background: rgba(0, 0, 0, .88);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: zoom-out;
  animation: fadeIn .2s ease;
  padding: 40px;
}
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
.lightbox-img {
  max-width: 90vw;
  max-height: 90vh;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, .6);
}
.lightbox-close {
  position: fixed;
  top: 20px;
  right: 24px;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, .2);
  background: rgba(255, 255, 255, .08);
  color: #fff;
  font-size: 18px;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: all .15s;
}
.lightbox-close:hover {
  background: rgba(255, 255, 255, .2);
  border-color: rgba(255, 255, 255, .4);
}
</style>
