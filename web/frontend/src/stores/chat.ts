import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ChatMessage } from '@/types'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const history = ref<{ role: string; content: string }[]>([])
  const currentConvId = ref<string | null>(null)
  const isStreaming = ref(false)
  const thinkingLines = ref<{ agent: string; content: string; done: boolean; type?: string }[]>([])
  const thinkingHeader = ref({ label: '', agent: '', active: false, done: false })
  const toolResults = ref<{ tool: string; server: string; result: any; elapsed_ms: number }[]>([])
  const toolHtmlParts = ref<string[]>([])
  const toolStatuses = ref<{ server: string; tool: string; status: string; ms: number; startTime: number }[]>([])
  const dividers = ref<string[]>([])
  const chainSuggestions = ref<{ label: string }[]>([])
  const totalTools = ref(0)
  const totalMs = ref(0)
  const lastExportData = ref<{ tool: string; server: string; result: any; ts: number }>({ tool: '', server: '', result: null, ts: 0 })
  const allExportData = ref<{ tool: string; result: any }[]>([])
  const pendingDrawMessage = ref<string>('')
  const events = ref<{ agent: string; action: string; detail: string }[]>([])
  const eventCount = ref(0)
  const pipelineName = ref('')
  const pipelineSteps = ref<{ id: number; tool: string; label: string; icon: string; status: string }[]>([])
  const pipelineActive = ref(false)

  const multiScenarioActive = ref(false)
  const multiScenarioName = ref('')
  const multiScenarioIcon = ref('')
  const scenarios = ref<{
    id: number; label: string;
    steps: { id: number; tool: string; label: string; icon: string; status: string }[];
    metrics: Record<string, number>;
  }[]>([])
  const comparisonResult = ref<{
    summary: string;
    metrics: { metric: string; key: string; values: { scenario_id: number; label: string; value: number }[]; delta_pct?: number }[];
  } | null>(null)

  const recentHistory = computed(() => history.value.slice(-10))

  function addUserMessage(content: string) {
    messages.value.push({
      id: `msg_${Date.now()}`,
      role: 'user',
      content,
      timestamp: Date.now(),
    })
    history.value.push({ role: 'user', content })
    saveHistory()
  }

  function addBotMessage(content: string) {
    messages.value.push({
      id: `msg_${Date.now()}`,
      role: 'assistant',
      content,
      timestamp: Date.now(),
    })
  }

  function updateLastBotMessage(content: string) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.content = content
    } else {
      messages.value.push({
        id: `msg_${Date.now()}`,
        role: 'assistant',
        content,
        timestamp: Date.now(),
      })
    }
  }

  function addThinkingLine(agent: string, content: string, done = false) {
    let type = ''
    if (content.match(/^━━━/)) type = 'step-header'
    else if (content.match(/^📋/)) type = 'step-goal'
    else if (content.match(/^🔍|^🎯|^🔄/)) type = 'step-decision'
    else if (content.match(/^❌/)) type = 'step-error'
    else if (content.match(/^✅|^📈/)) type = 'step-ok'
    thinkingLines.value.push({ agent, content, done, type })
  }

  function startThinking(agent: string, label: string) {
    thinkingHeader.value = { label, agent, active: true, done: false }
    thinkingLines.value = []
  }

  function closeThinking() {
    thinkingHeader.value.done = true
    thinkingHeader.value.active = false
    thinkingLines.value.forEach(l => l.done = true)
  }

  function markThinkingDone() {
    if (thinkingLines.value.length > 0) {
      thinkingLines.value[thinkingLines.value.length - 1].done = true
    }
  }

  function clearThinking() {
    thinkingLines.value = []
    thinkingHeader.value = { label: '', agent: '', active: false, done: false }
  }

  function addToolStatus(server: string, tool: string, status: string) {
    const key = `${server}.${tool}`
    const idx = toolStatuses.value.findIndex(t => `${t.server}.${t.tool}` === key)
    if (idx >= 0) {
      toolStatuses.value[idx].status = status
      if (status === 'ok' || status === 'error') {
        toolStatuses.value[idx].ms = Date.now() - toolStatuses.value[idx].startTime
      }
    } else {
      toolStatuses.value.push({ server, tool, status, ms: 0, startTime: Date.now() })
    }
  }

  function addDivider(text: string) {
    dividers.value.push(text)
  }

  function setChainSuggestions(suggestions: { label: string }[]) {
    chainSuggestions.value = suggestions
  }

  function addToolResult(tool: string, server: string, result: any, elapsed_ms = 0) {
    toolResults.value.push({ tool, server, result, elapsed_ms })
    totalTools.value++
    lastExportData.value = { tool, server, result, ts: Date.now() }
    if (result && !result.error) allExportData.value.push({ tool, result })
  }

  function addToolHtml(html: string) {
    if (html) toolHtmlParts.value.push(html)
  }

  function resetStreamState() {
    isStreaming.value = true
    thinkingLines.value = []
    thinkingHeader.value = { label: '', agent: '', active: false, done: false }
    toolResults.value = []
    toolHtmlParts.value = []
    toolStatuses.value = []
    dividers.value = []
    chainSuggestions.value = []
    pipelineName.value = ''
    pipelineSteps.value = []
    pipelineActive.value = false
    multiScenarioActive.value = false
    multiScenarioName.value = ''
    multiScenarioIcon.value = ''
    scenarios.value = []
    comparisonResult.value = null
    totalTools.value = 0
    totalMs.value = 0
  }

  function endStream() {
    isStreaming.value = false
    markThinkingDone()
  }

  function addEvent(agent: string, action: string, detail: string) {
    eventCount.value++
    events.value.unshift({ agent, action, detail })
  }

  function saveHistory() {
    try {
      localStorage.setItem('sai_chat_history', JSON.stringify(history.value.slice(-50)))
    } catch {}
  }

  function loadHistory() {
    try {
      const raw = localStorage.getItem('sai_chat_history')
      if (raw) history.value = JSON.parse(raw)
    } catch {}
  }

  loadHistory()

  return {
    messages, history, currentConvId, isStreaming,
    thinkingLines, thinkingHeader, toolResults, toolHtmlParts,
    toolStatuses, dividers, chainSuggestions,
    totalTools, totalMs,
    lastExportData, allExportData, events, eventCount,
    pipelineName, pipelineSteps, pipelineActive,
    multiScenarioActive, multiScenarioName, multiScenarioIcon,
    scenarios, comparisonResult,
    recentHistory,
    addUserMessage, addBotMessage, updateLastBotMessage,
    addThinkingLine, startThinking, closeThinking, markThinkingDone, clearThinking,
    addToolResult, addToolHtml, addToolStatus, addDivider, setChainSuggestions,
    resetStreamState, endStream, addEvent,
    pendingDrawMessage,
  }
})
