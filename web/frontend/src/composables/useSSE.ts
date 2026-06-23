import { useChatStore } from '@/stores/chat'
import { useToolRenderer } from '@/composables/useToolRenderer'
import type { SSEEvent } from '@/types'

type SSEHandler = (data: SSEEvent) => void

export function useSSE() {
  const chatStore = useChatStore()
  const toolRenderer = useToolRenderer()
  let currentES: EventSource | null = null

  const customHandlers = new Map<string, SSEHandler>()

  function register(type: string, handler: SSEHandler) {
    customHandlers.set(type, handler)
  }

  function esclose() {
    if (currentES) {
      try { currentES.close() } catch {}
      currentES = null
    }
  }

  const handlers: Record<string, SSEHandler> = {
    start: (data) => {
      if (data.conv_id) {
        chatStore.currentConvId = data.conv_id
        localStorage.setItem('sai_conv_id', String(data.conv_id))
      }
    },
    thinking_start: (data) => {
      chatStore.startThinking(data.agent || '', data.label || data.agent || '')
    },
    thinking: (data) => {
      chatStore.addThinkingLine(data.agent || '', data.content || '')
    },
    thinking_end: () => {
      chatStore.markThinkingDone()
      setTimeout(() => chatStore.closeThinking(), 300)
    },
    tool_start: (data) => {
      chatStore.addToolStatus(data.server || '', data.tool || '', 'running')
    },
    tool_end: (data) => {
      chatStore.addToolStatus(data.server || '', data.tool || '', data.error ? 'error' : 'ok')
    },
    tool_result: (data) => {
      if (data.result) {
        chatStore.addToolResult(data.tool, data.server, data.result, data.elapsed_ms || 0)
        const rendered = toolRenderer.render(data.tool, data.server, data.result)
        chatStore.addToolHtml(rendered.html)
        rendered.mapActions.forEach(fn => fn())
      }
    },
    tool_error: (data) => {
      chatStore.addThinkingLine('error', `❌ ${data.server}.${data.tool}: ${data.error || '未知错误'}`)
      chatStore.addToolStatus(data.server || '', data.tool || '', 'error')
    },
    divider: (data) => {
      chatStore.addDivider(data.content || '')
    },
    chain_suggestion: (data) => {
      if (data.suggestions) {
        chatStore.setChainSuggestions(data.suggestions)
      }
    },
    text: (data) => {
      chatStore.updateLastBotMessage(data.content || '')
    },
    done: () => {
      chatStore.endStream()
      const last = chatStore.messages[chatStore.messages.length - 1]
      chatStore.history.push({ role: 'assistant', content: last?.content || '' })
      esclose()
    },
  }

  function handleEvent(data: SSEEvent) {
    const handler = handlers[data.type] || customHandlers.get(data.type)
    handler?.(data)
  }

  function send(message: string) {
    if (currentES) {
      try { currentES.close() } catch {}
    }

    chatStore.addUserMessage(message)
    chatStore.resetStreamState()

    const wfList = Object.keys(JSON.parse(localStorage.getItem('wf_workflows') || '{}'))
    const wfParam = wfList.length ? `&workflows=${encodeURIComponent(JSON.stringify(wfList))}` : ''
    const convParam = chatStore.currentConvId ? `&conv_id=${chatStore.currentConvId}` : ''
    const historyParam = encodeURIComponent(JSON.stringify(chatStore.recentHistory.slice(0, -1)))

    const url = `/api/chat/stream?q=${encodeURIComponent(message)}&history=${historyParam}${wfParam}${convParam}`
    const es = new EventSource(url)
    currentES = es

    es.onmessage = (e) => {
      let data: SSEEvent
      try { data = JSON.parse(e.data) } catch { return }
      handleEvent(data)
    }

    es.onerror = () => {
      es.close()
      currentES = null
      chatStore.endStream()
      chatStore.addBotMessage('⚠️ 连接中断。请确保后端已启动: python web/server.py')
    }
  }

  return { send, close: esclose, register }
}
