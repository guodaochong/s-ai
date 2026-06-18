<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import L from 'leaflet'
import { useMapStore } from '@/stores/map'
import { useThreeStore } from '@/stores/three'
import { useChatStore } from '@/stores/chat'

const mapStore = useMapStore()
const threeStore = useThreeStore()
const chatStore = useChatStore()
const mapContainer = ref<HTMLDivElement>()
const threeContainer = ref<HTMLDivElement>()
const coordLabel = ref('LatLng: --')
const showLayerPanel = ref(false)
const showDrawPanel = ref(false)
const isDrawing = ref(false)
const drawnBbox = ref<number[]>([])
let initialized = false
let map: L.Map | null = null
let drawStart: L.LatLng | null = null
let currentRect: L.Rectangle | null = null

onMounted(() => {
  if (!mapContainer.value) return
  map = L.map(mapContainer.value, {
    center: [33.19, 104.89],
    zoom: 13,
    zoomControl: false,
    attributionControl: false,
  })
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19,
  }).addTo(map)
  mapStore.setMap(map)

  map.on('mousemove', (e: L.LeafletMouseEvent) => {
    coordLabel.value = `LatLng: ${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}`
  })

  const mc = map.getContainer()
  mc.addEventListener('mousedown', handleDomMouseDown)
  mc.addEventListener('mousemove', handleDomMouseMove)
  document.addEventListener('mouseup', handleDomMouseUp)
})

watch(() => threeStore.show3D, async (is3D) => {
  if (is3D && !initialized) {
    await nextTick()
    if (threeContainer.value) {
      threeStore.init3D(threeContainer.value)
      initialized = true
    }
  }
  if (!is3D) {
    threeStore.stopAnimation()
  }
})

onBeforeUnmount(() => {
  threeStore.dispose()
})

function flyTo(lat: number, lng: number, zoom: number) {
  map?.setView([lat, lng], zoom)
}

function toggleLayerPanel() {
  showLayerPanel.value = !showLayerPanel.value
}

function startDraw() {
  if (!map) return
  if (currentRect) { map.removeLayer(currentRect); currentRect = null }
  showDrawPanel.value = false
  isDrawing.value = true
  map.dragging.disable()
  map.getContainer().style.cursor = 'crosshair'
}

function stopDraw() {
  isDrawing.value = false
  drawStart = null
  if (map) {
    map.dragging.enable()
    map.getContainer().style.cursor = ''
  }
}

function getMapPoint(e: MouseEvent): L.Point {
  const rect = map!.getContainer().getBoundingClientRect()
  return L.point(e.clientX - rect.left, e.clientY - rect.top)
}

function handleDomMouseDown(e: MouseEvent) {
  if (!isDrawing.value || !map) return
  e.preventDefault()
  drawStart = map.containerPointToLatLng(getMapPoint(e))
  if (currentRect) { map.removeLayer(currentRect) }
  currentRect = L.rectangle([drawStart, drawStart], {
    color: '#00d4ff', weight: 2, fillColor: '#00d4ff', fillOpacity: 0.1, dashArray: '6 4',
  })
  currentRect.addTo(map)
}

function handleDomMouseMove(e: MouseEvent) {
  if (!isDrawing.value || !drawStart || !map || !currentRect) return
  const end = map.containerPointToLatLng(getMapPoint(e))
  currentRect.setBounds(L.latLngBounds(drawStart, end))
}

function handleDomMouseUp(e: MouseEvent) {
  if (!isDrawing.value || !drawStart || !map) return
  const end = map.containerPointToLatLng(getMapPoint(e))
  const bounds = L.latLngBounds(drawStart, end)
  if (Math.abs(bounds.getNorth() - bounds.getSouth()) < 0.001 ||
      Math.abs(bounds.getEast() - bounds.getWest()) < 0.001) {
    stopDraw()
    return
  }
  drawnBbox.value = [
    Math.round(bounds.getWest() * 1000) / 1000,
    Math.round(bounds.getSouth() * 1000) / 1000,
    Math.round(bounds.getEast() * 1000) / 1000,
    Math.round(bounds.getNorth() * 1000) / 1000,
  ]
  showDrawPanel.value = true
  stopDraw()
}

function clearDraw() {
  if (currentRect && map) { map.removeLayer(currentRect); currentRect = null }
  showDrawPanel.value = false
}

function triggerAnalysis(type: string) {
  if (drawnBbox.value.length !== 4) return
  const [w, s, e, n] = drawnBbox.value
  const bboxStr = `[${w},${s},${e},${n}]`
  const messages: Record<string, string> = {
    flood: `分析区域${bboxStr}暴雨150mm会不会淹`,
    building: `识别区域${bboxStr}的建筑`,
    precip: `展示区域${bboxStr}的降雨过程`,
    water: `监测区域${bboxStr}的水体`,
    drone: `规划区域${bboxStr}的无人机巡查航线`,
  }
  const msg = messages[type] || ''
  if (!msg) return
  showDrawPanel.value = false
  chatStore.pendingDrawMessage = msg
}

function removeLayer(id: string) {
  mapStore.removeLayerById(id)
}

function addDemoLayer() {
  mapStore.clearAll()
  const l = L.geoJSON({
    type: 'FeatureCollection',
    features: [
      { type: 'Feature', geometry: { type: 'Polygon', coordinates: [[[116.28, 39.82], [116.48, 39.82], [116.48, 40.02], [116.28, 40.02], [116.28, 39.82]]] }, properties: { name: '分析区域A', risk: 'high' } },
      { type: 'Feature', geometry: { type: 'Point', coordinates: [116.397, 39.908] }, properties: { name: '天安门', type: 'landmark' } },
      { type: 'Feature', geometry: { type: 'Point', coordinates: [116.391, 39.914] }, properties: { name: '故宫', type: 'landmark' } },
      { type: 'Feature', geometry: { type: 'LineString', coordinates: [[116.28, 39.88], [116.35, 39.90], [116.40, 39.91], [116.48, 39.92]] }, properties: { name: '主干排水管线', type: 'pipe' } },
    ],
  }, {
    style: (f: any) => ({
      color: f?.properties?.risk === 'high' ? '#f59e0b' : '#00d4ff',
      weight: 2,
      fillOpacity: .15,
      dashArray: f?.properties?.type === 'pipe' ? '5 10' : undefined,
    }),
    pointToLayer: (_f: any, ll: L.LatLng) => L.circleMarker(ll, { radius: 6, fillColor: '#00d4ff', fillOpacity: .8, color: '#fff', weight: 1 }),
    onEachFeature: (f: any, layer: L.Layer) => {
      if (f.properties) (layer as L.GeoJSON).bindPopup(`<b>${f.properties.name}</b><br>${JSON.stringify(f.properties)}`)
    },
  })
  const id = mapStore.addLayer(l, '示例图层')
  try { map?.fitBounds(l.getBounds().pad(.1)) } catch {}
}
</script>

<template>
  <div class="map-panel">
    <div ref="mapContainer" id="map" v-show="!threeStore.show3D" />
    <div ref="threeContainer" id="terrain3d" v-show="threeStore.show3D" />

    <div class="map-overlay">
      <button class="map-btn" @click="flyTo(39.9042, 116.4074, 10)">● 北京</button>
      <button class="map-btn" @click="flyTo(22.5431, 114.0579, 10)">● 深圳</button>
      <button class="map-btn" @click="addDemoLayer">▶ 加载示例图层</button>
      <button class="map-btn" @click="threeStore.toggle3D()">
        {{ threeStore.show3D ? '■ 2D地图' : '△ 3D地形' }}
      </button>
      <button class="map-btn" @click="toggleLayerPanel()" title="图层管理">☰ 图层</button>
      <button class="map-btn" @click="startDraw()" title="画框分析" style="color:#00ff88;border-color:#00ff88">{{ isDrawing ? '✏ 拖拽画框...' : '✏ 画框分析' }}</button>
    </div>

    <div v-if="showDrawPanel" class="draw-panel">
      <div class="dp-header">
        <span>📍 选定区域分析</span>
        <button class="dp-close" @click="clearDraw">✕</button>
      </div>
      <div class="dp-bbox">bbox: [{{ drawnBbox.map(v => v.toFixed(3)).join(', ') }}]</div>
      <div class="dp-actions">
        <button class="dp-btn" @click="triggerAnalysis('flood')">🌊 会淹吗？</button>
        <button class="dp-btn" @click="triggerAnalysis('building')">🏙️ 识别建筑</button>
        <button class="dp-btn" @click="triggerAnalysis('precip')">🌧️ 降雨过程</button>
        <button class="dp-btn" @click="triggerAnalysis('water')">🌊 水体监测</button>
        <button class="dp-btn" @click="triggerAnalysis('drone')">🚁 无人机航线</button>
      </div>
    </div>

    <div class="map-toolbar">
      <button class="tb-btn" @click="map?.zoomIn()" title="放大">＋</button>
      <button class="tb-btn" @click="map?.zoomOut()" title="缩小">－</button>
    </div>

    <div v-if="showLayerPanel" class="layer-panel">
      <div class="lp-title">图层管理</div>
      <div v-if="mapStore.layers.length === 0" class="lp-empty">暂无图层</div>
      <div v-for="layer in mapStore.layers" :key="layer.id" class="lp-item">
        <span class="lp-dot" />
        <span class="lp-name">{{ layer.name }}</span>
        <button class="lp-rm" @click="removeLayer(layer.id)">✕</button>
      </div>
    </div>

    <div class="map-info">{{ coordLabel }}</div>

    <div v-if="threeStore.show3D" class="water-control">
      <div class="wc-title">🌊 水位控制</div>
      <input
        type="range" min="0" max="100" :value="threeStore.waterLevel"
        @input="threeStore.setWaterLevel(+($event.target as HTMLInputElement).value)"
      />
      <span class="wc-label">{{ threeStore.waterLabel }}</span>
    </div>

    <div v-if="threeStore.hydroFrames.length > 0" class="hydro-timeline">
      <div class="ht-row">
        <span>🎬</span>
        <button class="ht-play" @click="threeStore.hydroPlayToggle()">
          {{ threeStore.hydroPlaying ? '⏸ PAUSE' : '▶ PLAY' }}
        </button>
        <input
          type="range" min="0" :max="Math.max(0, threeStore.hydroFrames.length - 1)"
          :value="threeStore.hydroIdx"
          @input="threeStore.hydroSeek(+($event.target as HTMLInputElement).value)"
          class="ht-range"
        />
        <span class="ht-time">{{ threeStore.hydroTimeLabel }}</span>
      </div>
      <div class="ht-row ht-controls">
        <span class="ht-dim">Speed:</span>
        <button
          v-for="s in [1, 2, 4]" :key="s"
          :class="['ht-speed', { active: threeStore.hydroSpeedVal === s }]"
          @click="threeStore.setHydroSpeed(s)"
        >{{ s }}x</button>
        <span class="ht-info">{{ threeStore.hydroInfo }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.map-panel {
  grid-column: 2;
  grid-row: 2;
  background: var(--bg-deep);
  position: relative;
  overflow: hidden;
}
#map {
  width: 100%;
  height: 100%;
  z-index: 1;
}
#terrain3d {
  width: 100%;
  height: 100%;
  position: absolute;
  top: 0;
  left: 0;
  z-index: 1;
}
.map-overlay {
  position: absolute;
  top: 16px;
  left: 16px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.map-btn {
  background: rgba(13, 19, 33, .8);
  backdrop-filter: var(--glass);
  -webkit-backdrop-filter: var(--glass);
  border: 1px solid rgba(255, 255, 255, .08);
  color: var(--text);
  padding: 8px 16px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: 12px;
  font-family: 'JetBrains Mono', monospace;
  transition: all .25s;
  box-shadow: var(--shadow-sm);
}
.map-btn:hover {
  border-color: rgba(0, 212, 255, .4);
  color: var(--accent);
  box-shadow: var(--glow);
}
.map-toolbar {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 1000;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.tb-btn {
  width: 38px;
  height: 38px;
  border-radius: var(--radius-sm);
  background: rgba(13, 19, 33, .8);
  backdrop-filter: var(--glass);
  -webkit-backdrop-filter: var(--glass);
  border: 1px solid rgba(255, 255, 255, .08);
  color: var(--text-dim);
  cursor: pointer;
  display: grid;
  place-items: center;
  font-size: 16px;
  transition: all .25s;
  box-shadow: var(--shadow-sm);
}
.tb-btn:hover {
  border-color: rgba(0, 212, 255, .4);
  color: var(--accent);
  box-shadow: var(--glow);
}
.layer-panel {
  position: absolute;
  top: 60px;
  right: 16px;
  z-index: 1001;
  background: rgba(13, 19, 33, .95);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, .08);
  border-radius: var(--radius-sm);
  padding: 10px 0;
  min-width: 180px;
  box-shadow: var(--shadow-md);
}
.lp-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-dim);
  padding: 4px 14px 8px;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.lp-empty {
  font-size: 11px;
  color: var(--text-dim);
  padding: 6px 14px;
}
.lp-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 14px;
  font-size: 11px;
  color: var(--text);
  transition: background .2s;
}
.lp-item:hover { background: rgba(0, 212, 255, .04); }
.lp-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
}
.lp-name { flex: 1; }
.lp-rm {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 10px;
  padding: 2px 4px;
  border-radius: 3px;
}
.lp-rm:hover { color: var(--danger); background: rgba(239, 68, 68, .1); }
.map-info {
  position: absolute;
  bottom: 16px;
  left: 16px;
  z-index: 1000;
  background: rgba(13, 19, 33, .85);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, .08);
  border-radius: var(--radius-sm);
  padding: 10px 16px;
  font-size: 11px;
  font-family: 'JetBrains Mono', monospace;
  color: var(--text-dim);
  box-shadow: var(--shadow-md);
}
.water-control {
  position: absolute;
  bottom: 50px;
  left: 10px;
  z-index: 1000;
  background: rgba(13, 19, 33, .92);
  border: 1px solid rgba(255, 255, 255, .08);
  border-radius: 8px;
  padding: 10px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.wc-title {
  color: var(--accent);
  font-weight: 700;
  white-space: nowrap;
}
.wc-label {
  color: var(--text);
  font-size: 11px;
  min-width: 60px;
}
.hydro-timeline {
  position: absolute;
  bottom: 8px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1000;
  background: rgba(13, 17, 23, .95);
  border: 1px solid rgba(0, 212, 255, .15);
  border-radius: 8px;
  padding: 8px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 580px;
  max-width: calc(100% - 20px);
}
.ht-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}
.ht-play {
  background: var(--accent);
  color: #000;
  border: none;
  border-radius: 4px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 700;
}
.ht-range { flex: 1; accent-color: var(--accent); }
.ht-time {
  color: var(--text);
  font-size: 11px;
  min-width: 36px;
  font-family: 'JetBrains Mono', monospace;
}
.ht-controls { font-size: 10px; }
.ht-dim { color: var(--text-dim); }
.ht-speed {
  background: rgba(13, 19, 33, .9);
  border: 1px solid rgba(0, 212, 255, .15);
  color: var(--text-dim);
  padding: 2px 8px;
  border-radius: 3px;
  cursor: pointer;
  font-size: 10px;
  font-family: 'JetBrains Mono', monospace;
}
.ht-speed:hover { border-color: var(--accent); color: var(--accent); }
.ht-speed.active { background: var(--accent); color: #000; border-color: var(--accent); }
.ht-info { margin-left: auto; color: var(--text-dim); font-size: 10px; }

.draw-panel {
  position: absolute;
  top: 60px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 1001;
  background: rgba(8, 14, 28, 0.95);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(0, 255, 136, 0.2);
  border-radius: 12px;
  padding: 12px 16px;
  min-width: 280px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}
.draw-panel .dp-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 700;
  color: #00ff88;
  margin-bottom: 6px;
}
.draw-panel .dp-close {
  width: 22px; height: 22px;
  border-radius: 6px; border: none;
  background: rgba(255,255,255,0.05);
  color: #94a3b8; cursor: pointer;
  font-size: 11px;
}
.draw-panel .dp-close:hover { background: rgba(239,68,68,0.15); color: #ef4444; }
.draw-panel .dp-bbox {
  font-size: 10px;
  color: #64748b;
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 8px;
}
.draw-panel .dp-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}
.draw-panel .dp-btn {
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid rgba(0, 212, 255, 0.15);
  background: rgba(0, 212, 255, 0.06);
  color: #e2e8f0;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
  text-align: left;
}
.draw-panel .dp-btn:hover {
  background: rgba(0, 212, 255, 0.15);
  border-color: rgba(0, 212, 255, 0.4);
  color: #00d4ff;
}
</style>
