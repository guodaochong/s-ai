import { useChatStore } from '@/stores/chat'
import { useToolRenderer } from '@/composables/useToolRenderer'
import type { SSEEvent } from '@/types'

export function useSSE() {
  const chatStore = useChatStore()
  const toolRenderer = useToolRenderer()
  let currentES: EventSource | null = null

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

  function handleEvent(data: SSEEvent) {
    switch (data.type) {
      case 'start':
        if (data.conv_id) {
          chatStore.currentConvId = data.conv_id
          localStorage.setItem('sai_conv_id', String(data.conv_id))
        }
        break

      case 'thinking_start':
        chatStore.startThinking(data.agent || '', data.label || data.agent || '')
        break

      case 'thinking':
        chatStore.addThinkingLine(data.agent || '', data.content || '')
        break

      case 'thinking_end':
        chatStore.markThinkingDone()
        setTimeout(() => chatStore.closeThinking(), 300)
        break

      case 'tool_start':
        chatStore.addToolStatus(data.server || '', data.tool || '', 'running')
        break

      case 'tool_end':
        chatStore.addToolStatus(data.server || '', data.tool || '', data.error ? 'error' : 'ok')
        break

      case 'tool_result':
        if (data.result) {
          chatStore.addToolResult(data.tool, data.server, data.result, data.elapsed_ms || 0)
          const rendered = toolRenderer.render(data.tool, data.server, data.result)
          chatStore.addToolHtml(rendered.html)
          rendered.mapActions.forEach(fn => fn())
        }
        break

      case 'tool_error':
        chatStore.addThinkingLine('error', `❌ ${data.server}.${data.tool}: ${data.error || '未知错误'}`)
        chatStore.addToolStatus(data.server || '', data.tool || '', 'error')
        break

      case 'divider':
        chatStore.addDivider(data.content || '')
        break

      case 'chain_suggestion':
        if (data.suggestions) {
          chatStore.setChainSuggestions(data.suggestions)
        }
        break

      case 'text':
        chatStore.updateLastBotMessage(data.content || '')
        break

      case 'done':
        chatStore.endStream()
        {
          const last = chatStore.messages[chatStore.messages.length - 1]
          chatStore.history.push({ role: 'assistant', content: last?.content || '' })
        }
        esclose()
        break
    }
  }

  function esclose() {
    if (currentES) {
      try { currentES.close() } catch {}
      currentES = null
    }
  }

  return { send, close: esclose }
}
