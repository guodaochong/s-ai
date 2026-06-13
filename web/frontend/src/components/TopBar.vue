<script setup lang="ts">
import { onMounted, onUnmounted, ref, defineExpose } from 'vue'
import { useServices } from '@/composables/useServices'
import { useChatStore } from '@/stores/chat'
import { useMapStore } from '@/stores/map'

const { services, refresh, serviceCount } = useServices()
const chatStore = useChatStore()
const mapStore = useMapStore()
let timer: ReturnType<typeof setInterval>

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 10000)
})

onUnmounted(() => {
  clearInterval(timer)
})

const emit = defineEmits<{ (e: 'openRecon'): void; (e: 'openWorkflow'): void }>()

const showSvcPanel = ref(false)
</script>

<template>
  <header class="topbar">
    <div class="logo">
      <div class="icon">⊛</div>
      <span class="brand">S-AI</span>
      <span class="subtitle">水利空间智能体平台</span>
    </div>
    <div class="status-pills">
      <span
        v-for="svc in services"
        :key="svc.name"
        class="pill"
        :class="svc.healthy ? 'ok' : 'off'"
      >
        <span class="dot" />
        {{ svc.name }}
      </span>
    </div>
    <div class="meta">
      <span class="meta-val">{{ serviceCount.tools }}</span> tools
      <span class="meta-sep">|</span>
      <span class="meta-val">{{ serviceCount.healthy }}</span>/{{ serviceCount.total }} svc
    </div>
    <div class="topbar-actions">
      <button class="topbar-btn" @click="showSvcPanel = !showSvcPanel" :class="{ active: showSvcPanel }" title="服务状态">
        📊 服务
      </button>
      <button class="topbar-btn recon-btn" @click="emit('openRecon')" title="AI 三维重建">
        🧊 3D重建
      </button>
    </div>
  </header>

  <Teleport to="body">
    <Transition name="svc-slide">
      <div v-if="showSvcPanel" class="svc-float-panel">
        <div class="svc-float-header">
          <span>系统监控</span>
          <button class="svc-float-close" @click="showSvcPanel = false">✕</button>
        </div>
        <div class="svc-float-section">
          <div class="svc-float-title">系统信息</div>
          <div class="svc-float-info">
            <div class="svc-float-row"><span>MCP Servers</span><span class="v-green">{{ serviceCount.healthy }}/{{ serviceCount.total }}</span></div>
            <div class="svc-float-row"><span>Tools</span><span class="v-cyan">{{ serviceCount.tools }}</span></div>
            <div class="svc-float-row"><span>Events</span><span class="v-purple">{{ chatStore.eventCount }}</span></div>
            <div class="svc-float-row"><span>图层</span><span class="v-cyan">{{ mapStore.layers.length }}</span></div>
          </div>
        </div>
        <div class="svc-float-section">
          <div class="svc-float-title">服务状态</div>
          <div class="svc-float-svcs">
            <div v-for="svc in services" :key="svc.name" class="svc-float-svc">
              <span class="svc-float-dot" :style="{ background: svc.healthy ? '#10b981' : '#ef4444' }" />
              <span class="svc-float-name">{{ svc.name }}</span>
              <span :class="['svc-float-st', svc.healthy ? 'ok' : 'err']">{{ svc.healthy ? '在线' : '离线' }}</span>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.topbar {
  grid-column: 1 / -1;
  grid-row: 1;
  background: var(--bg-panel);
  backdrop-filter: var(--glass);
  -webkit-backdrop-filter: var(--glass);
  display: flex;
  align-items: center;
  padding: 0 24px;
  gap: 16px;
  border-bottom: var(--glass-border);
  position: relative;
  z-index: 10;
}
.topbar::after {
  content: '';
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--gradient-accent);
  opacity: .3;
}
.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 18px;
  font-weight: 900;
  letter-spacing: 3px;
}
.brand {
  background: var(--gradient-accent);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-size: 200% 200%;
  animation: gradientShift 4s ease infinite;
}
.icon {
  width: 32px;
  height: 32px;
  background: var(--gradient-accent);
  border-radius: 8px;
  display: grid;
  place-items: center;
  font-size: 16px;
  box-shadow: 0 0 16px rgba(0, 212, 255, .3);
  animation: iconPulse 3s ease infinite;
}
.subtitle {
  font-weight: 300;
  font-size: 12px;
  color: var(--text-dim);
  letter-spacing: 0;
}
.status-pills {
  display: flex;
  gap: 8px;
  margin-left: auto;
}
.pill {
  font-size: 11px;
  padding: 4px 12px;
  border-radius: 20px;
  font-family: 'JetBrains Mono', monospace;
  display: flex;
  align-items: center;
  gap: 6px;
  backdrop-filter: blur(4px);
}
.pill.ok {
  background: rgba(16, 185, 129, .1);
  color: var(--accent3);
  border: 1px solid rgba(16, 185, 129, .2);
}
.pill.off {
  background: rgba(100, 116, 139, .08);
  color: var(--text-dim);
  border: 1px solid rgba(100, 116, 139, .15);
}
.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
  animation: pulse 2s infinite;
}
.meta {
  font-size: 11px;
  color: var(--text-dim);
  font-family: 'JetBrains Mono', monospace;
  display: flex;
  align-items: center;
  gap: 6px;
}
.meta-val { color: var(--accent); }
.meta-sep { opacity: .3; }
.topbar-actions {
  margin-left: 12px;
}
.topbar-btn {
  font-size: 12px;
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid var(--border-solid);
  background: var(--bg-card);
  color: var(--text);
  cursor: pointer;
  transition: all 0.15s;
}
.topbar-btn:hover {
  border-color: var(--accent);
  color: var(--accent);
  box-shadow: var(--glow);
}
.topbar-btn.active {
  border-color: var(--accent);
  color: var(--accent);
  background: rgba(0, 212, 255, .08);
}
</style>

<style>
.svc-float-panel {
  position: fixed;
  top: 56px;
  right: 0;
  width: 300px;
  max-height: calc(100vh - 56px);
  overflow-y: auto;
  background: rgba(10, 14, 26, .95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-left: 1px solid rgba(0, 212, 255, .15);
  border-bottom: 1px solid rgba(0, 212, 255, .15);
  z-index: 9000;
  box-shadow: -8px 8px 32px rgba(0, 0, 0, .4);
}
.svc-float-panel::-webkit-scrollbar { width: 4px; }
.svc-float-panel::-webkit-scrollbar-thumb { background: rgba(0, 212, 255, .2); border-radius: 2px; }

.svc-slide-enter-active,
.svc-slide-leave-active {
  transition: transform .3s cubic-bezier(.4, 0, .2, 1), opacity .2s ease;
}
.svc-slide-enter-from,
.svc-slide-leave-to {
  transform: translateX(320px);
  opacity: 0;
}

.svc-float-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 1px;
  border-bottom: 1px solid rgba(0, 212, 255, .1);
}
.svc-float-close {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: 1px solid rgba(255, 255, 255, .1);
  background: transparent;
  color: var(--text-dim, #8899aa);
  cursor: pointer;
  font-size: 12px;
  transition: all .15s;
}
.svc-float-close:hover {
  color: #ff6b6b;
  border-color: rgba(255, 107, 107, .3);
}

.svc-float-section {
  padding: 12px 16px;
}
.svc-float-section + .svc-float-section {
  border-top: 1px solid rgba(255, 255, 255, .04);
}
.svc-float-title {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 2px;
  color: #667788;
  font-weight: 700;
  margin-bottom: 10px;
}
.svc-float-info {
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  line-height: 2;
}
.svc-float-row {
  display: flex;
  justify-content: space-between;
}
.v-green { color: #10b981; }
.v-cyan { color: #00d4ff; }
.v-purple { color: #c084fc; }

.svc-float-svcs {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.svc-float-svc {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 12px;
  transition: background .15s;
}
.svc-float-svc:hover {
  background: rgba(0, 212, 255, .04);
}
.svc-float-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 6px currentColor;
}
.svc-float-name {
  flex: 1;
  color: #94a3b8;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
}
.svc-float-st { font-size: 10px; }
.svc-float-st.ok { color: #10b981; }
.svc-float-st.err { color: #ef4444; }
</style>
