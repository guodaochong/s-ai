<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import L from 'leaflet'
import { useMapStore } from '@/stores/map'
import { useThreeStore } from '@/stores/three'

const mapStore = useMapStore()
const threeStore = useThreeStore()
const mapContainer = ref<HTMLDivElement>()
const threeContainer = ref<HTMLDivElement>()
const coordLabel = ref('LatLng: --')
const showLayerPanel = ref(false)
let initialized = false
let map: L.Map | null = null

onMounted(() => {
  if (!mapContainer.value) return
  map = L.map(mapContainer.value, {
    center: [33.19, 104.89],
    zoom: 13,
    zoomControl: false,
  })
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19,
  }).addTo(map)
  mapStore.setMap(map)

  map.on('mousemove', (e: L.LeafletMouseEvent) => {
    coordLabel.value = `LatLng: ${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}`
  })
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
</style>
