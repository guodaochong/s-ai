<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import TopBar from '@/components/TopBar.vue'
import SideBar from '@/components/SideBar.vue'
import MapPanel from '@/components/MapPanel.vue'
import ChatPanel from '@/components/ChatPanel.vue'
import WorkflowEditor from '@/components/WorkflowEditor.vue'
import ReconstructionPanel from '@/components/ReconstructionPanel.vue'
import { useChatStore } from '@/stores/chat'

const chatStore = useChatStore()
const eventsOpen = ref(false)
const reconOpen = ref(false)

const reconResultUrl = ref<string | null>(null)

;(window as any).__openReconResult = (url: string) => {
  reconResultUrl.value = url
  reconOpen.value = true
}

onUnmounted(() => {
  delete (window as any).__openReconResult
})
</script>

<template>
  <div class="app-grid">
    <TopBar @openRecon="reconOpen = true" />
    <SideBar />
    <MapPanel />
    <ChatPanel />
    <WorkflowEditor />

    <div :class="['events-panel', { open: eventsOpen }]">
      <div class="events-header" @click="eventsOpen = !eventsOpen">
        <span>◆ 事件流 (EVENT BACKLOG) — {{ chatStore.eventCount }}</span>
        <span>{{ eventsOpen ? '▲' : '▼' }}</span>
      </div>
      <div class="events-list">
        <span v-for="(evt, i) in chatStore.events" :key="i" class="event-chip">
          <span class="evt-agent">{{ evt.agent }}</span> → {{ evt.action }} <span class="evt-detail">{{ evt.detail.slice(0, 30) }}</span>
        </span>
      </div>
    </div>
  </div>

  <ReconstructionPanel v-model:show="reconOpen" :initialGlbUrl="reconResultUrl" />
</template>

<style scoped>
.app-grid {
  display: grid;
  grid-template-columns: 260px 1fr 460px;
  grid-template-rows: 56px 1fr auto;
  height: 100vh;
  gap: 1px;
  background: var(--border-solid);
}
.events-panel {
  grid-column: 1 / -1;
  background: var(--bg-panel);
  border-top: var(--glass-border);
  height: 0;
  overflow: hidden;
  transition: height .3s cubic-bezier(.4, 0, .2, 1);
}
.events-panel.open {
  height: 140px;
}
.events-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  font-size: 11px;
  color: var(--text-dim);
  cursor: pointer;
  letter-spacing: 1px;
  user-select: none;
}
.events-header:hover { color: var(--text); }
.events-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px 16px 8px;
  overflow-y: auto;
  max-height: 100px;
}
.event-chip {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-dim);
  font-family: 'JetBrains Mono', monospace;
}
.evt-agent { color: var(--accent); }
.evt-detail { color: #8899aa; }
</style>
