<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useServices } from '@/composables/useServices'

const { services, refresh, serviceCount } = useServices()
let timer: ReturnType<typeof setInterval>

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 10000)
})

onUnmounted(() => {
  clearInterval(timer)
})
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
  </header>
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
</style>
