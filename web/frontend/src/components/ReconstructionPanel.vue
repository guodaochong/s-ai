<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'

const API = '/api'

const show = defineModel<boolean>('show', { default: false })
const props = defineProps<{ initialGlbUrl?: string | null }>()

type ReconStage = 'queued' | 'loading_model' | 'preprocessing' | 'inference' | 'extracting_mesh' | 'exporting' | 'done' | 'error'

interface ReconState {
  stage: ReconStage
  progress: number
  detail: string
  meta: any
  error: string | null
  glbUrl: string | null
}

const state = ref<ReconState>({
  stage: 'queued',
  progress: 0,
  detail: '',
  meta: null,
  error: null,
  glbUrl: null,
})

const dragOver = ref(false)
const previewUrl = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const viewerContainer = ref<HTMLDivElement | null>(null)

let threeScene: THREE.Scene | null = null
let threeRenderer: THREE.WebGLRenderer | null = null
let threeCamera: THREE.PerspectiveCamera | null = null
let threeControls: OrbitControls | null = null
let animFrame = 0
let pollTimer = 0

const stageLabels: Record<ReconStage, string> = {
  queued: '排队中',
  loading_model: '加载 TripoSR 模型',
  preprocessing: '图像预处理 (背景去除)',
  inference: 'AI 推理中',
  extracting_mesh: '提取网格',
  exporting: '导出 GLB',
  done: '完成',
  error: '错误',
}

const stageColors: Record<ReconStage, string> = {
  queued: '#64748b',
  loading_model: '#f59e0b',
  preprocessing: '#00d4ff',
  inference: '#7c3aed',
  extracting_mesh: '#00d4ff',
  exporting: '#10b981',
  done: '#10b981',
  error: '#ef4444',
}

function handleDrop(e: DragEvent) {
  e.preventDefault()
  dragOver.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file) startReconstruction(file)
}

function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) startReconstruction(file)
}

async function startReconstruction(file: File) {
  state.value = {
    stage: 'queued',
    progress: 0,
    detail: '上传中...',
    meta: null,
    error: null,
    glbUrl: null,
  }
  previewUrl.value = URL.createObjectURL(file)

  const formData = new FormData()
  formData.append('file', file)

  try {
    const resp = await fetch(`${API}/reconstruct/upload`, {
      method: 'POST',
      body: formData,
    })
    const data = await resp.json()
    if (data.error) {
      state.value.stage = 'error'
      state.value.error = data.error
      return
    }
    pollStatus(data.task_id)
  } catch (err: any) {
    state.value.stage = 'error'
    state.value.error = err.message
  }
}

function pollStatus(taskId: string) {
  clearInterval(pollTimer)
  pollTimer = window.setInterval(async () => {
    try {
      const resp = await fetch(`${API}/reconstruct/status/${taskId}`)
      const data = await resp.json()
      state.value.stage = data.stage
      state.value.progress = data.progress
      state.value.detail = data.detail
      if (data.meta) state.value.meta = data.meta
      if (data.error) {
        state.value.error = data.error
        clearInterval(pollTimer)
      }
      if (data.stage === 'done' && data.output) {
        state.value.glbUrl = `${API}/reconstruct/result/${taskId}`
        clearInterval(pollTimer)
        setTimeout(() => loadGLB(state.value.glbUrl!), 200)
      }
    } catch (err) {
      clearInterval(pollTimer)
    }
  }, 800)
}

function initThreeViewer() {
  if (!viewerContainer.value) return
  const container = viewerContainer.value
  const w = container.clientWidth
  const h = container.clientHeight

  threeScene = new THREE.Scene()
  threeScene.background = new THREE.Color(0x0a0f1c)

  threeCamera = new THREE.PerspectiveCamera(45, w / h, 0.01, 100)
  threeCamera.position.set(2, 1.5, 2.5)

  threeRenderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
  threeRenderer.setSize(w, h)
  threeRenderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  threeRenderer.outputColorSpace = THREE.SRGBColorSpace
  threeRenderer.toneMapping = THREE.ACESFilmicToneMapping
  threeRenderer.toneMappingExposure = 1.2
  container.appendChild(threeRenderer.domElement)

  threeControls = new OrbitControls(threeCamera, threeRenderer.domElement)
  threeControls.enableDamping = true
  threeControls.dampingFactor = 0.08
  threeControls.autoRotate = true
  threeControls.autoRotateSpeed = 0.8

  const amb = new THREE.AmbientLight(0x404060, 0.6)
  threeScene.add(amb)
  const dir1 = new THREE.DirectionalLight(0xffffff, 1.2)
  dir1.position.set(3, 5, 3)
  threeScene.add(dir1)
  const dir2 = new THREE.DirectionalLight(0x00d4ff, 0.4)
  dir2.position.set(-3, 2, -3)
  threeScene.add(dir2)

  const grid = new THREE.GridHelper(4, 20, 0x1e293b, 0x1e293b)
  ;(grid.material as THREE.Material).opacity = 0.3
  ;(grid.material as THREE.Material).transparent = true
  threeScene.add(grid)

  animate()
}

function animate() {
  animFrame = requestAnimationFrame(animate)
  if (threeControls) threeControls.update()
  if (threeRenderer && threeScene && threeCamera) {
    threeRenderer.render(threeScene, threeCamera)
  }
}

function loadGLB(url: string) {
  if (!threeScene) initThreeViewer()

  const loader = new GLTFLoader()
  loader.load(
    url,
    (gltf) => {
      const model = gltf.scene
      const box = new THREE.Box3().setFromObject(model)
      const size = box.getSize(new THREE.Vector3())
      const center = box.getCenter(new THREE.Vector3())
      const maxDim = Math.max(size.x, size.y, size.z)
      const scale = 2.0 / maxDim
      model.scale.setScalar(scale)
      model.position.x = -center.x * scale
      model.position.y = -center.y * scale + 1.0
      model.position.z = -center.z * scale

      threeScene!.add(model)

      if (threeCamera) {
        threeCamera.position.set(2.5, 1.8, 2.5)
        threeCamera.lookAt(0, 0.5, 0)
      }
    },
    (xhr) => {
      console.log(`GLB ${(xhr.loaded / xhr.total * 100).toFixed(0)}%`)
    },
    (err) => {
      console.error('GLB load error:', err)
    },
  )
}

function closePanel() {
  show.value = false
}

function resetPanel() {
  state.value = {
    stage: 'queued',
    progress: 0,
    detail: '',
    meta: null,
    error: null,
    glbUrl: null,
  }
  previewUrl.value = null
  if (threeScene) {
    threeScene.clear()
    initThreeViewer()
  }
}

watch(show, (v) => {
  if (v) {
    setTimeout(() => {
      if (!threeRenderer && viewerContainer.value) {
        initThreeViewer()
      }
      if (props.initialGlbUrl) {
        state.value.glbUrl = props.initialGlbUrl
        state.value.stage = 'done'
        state.value.progress = 100
        loadGLB(props.initialGlbUrl)
      }
    }, 100)
  }
})

watch(() => props.initialGlbUrl, (url) => {
  if (url && show.value) {
    state.value.glbUrl = url
    state.value.stage = 'done'
    state.value.progress = 100
    loadGLB(url)
  }
})

onUnmounted(() => {
  cancelAnimationFrame(animFrame)
  clearInterval(pollTimer)
  if (threeRenderer) {
    threeRenderer.dispose()
    threeRenderer = null
  }
})
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="recon-overlay" @click.self="closePanel">
      <div class="recon-panel">
        <div class="recon-header">
          <div class="recon-title">
            <span class="recon-icon">🧊</span>
            AI 三维重建 · TripoSR
          </div>
          <div class="recon-header-actions">
            <button v-if="state.glbUrl" class="recon-btn-sm" @click="resetPanel">↻ 新建</button>
            <a v-if="state.glbUrl" class="recon-btn-sm download" :href="state.glbUrl" download>⬇ GLB</a>
            <button class="recon-btn-sm close" @click="closePanel">✕</button>
          </div>
        </div>

        <div class="recon-body">
          <div class="recon-left">
            <div
              v-if="!state.glbUrl && state.stage !== 'done'"
              class="upload-zone"
              :class="{ dragover: dragOver, processing: state.stage !== 'queued' }"
              @dragover.prevent="dragOver = true"
              @dragleave="dragOver = false"
              @drop="handleDrop"
              @click="state.stage === 'queued' ? fileInput?.click() : null"
            >
              <input
                ref="fileInput"
                type="file"
                accept="image/*"
                style="display:none"
                @change="handleFileSelect"
              />
              <template v-if="state.stage === 'queued'">
                <div class="upload-icon">📷</div>
                <div class="upload-text">拖拽照片或点击上传</div>
                <div class="upload-hint">支持 PNG / JPG / BMP / WEBP — 单张照片秒出 3D 模型</div>
              </template>
              <template v-else>
                <div class="processing-spinner" :style="{ borderColor: stageColors[state.stage] }"></div>
                <div class="processing-stage" :style="{ color: stageColors[state.stage] }">
                  {{ stageLabels[state.stage] }}
                </div>
                <div class="processing-detail">{{ state.detail }}</div>
              </template>
            </div>

            <div v-if="state.stage !== 'queued' && state.stage !== 'done' && state.stage !== 'error'" class="progress-bar-container">
              <div class="progress-bar" :style="{ width: state.progress + '%', background: stageColors[state.stage] }"></div>
              <div class="progress-text">{{ state.progress }}%</div>
            </div>

            <div v-if="previewUrl && state.stage !== 'queued'" class="preview-section">
              <div class="preview-label">输入图像</div>
              <img :src="previewUrl" class="preview-img" />
            </div>

            <div v-if="state.error" class="error-box">
              <div class="error-title">⚠ 重建失败</div>
              <pre class="error-detail">{{ state.error }}</pre>
            </div>

            <div v-if="state.meta" class="meta-grid">
              <div class="meta-item">
                <div class="meta-value">{{ state.meta.vertices?.toLocaleString() }}</div>
                <div class="meta-label">顶点</div>
              </div>
              <div class="meta-item">
                <div class="meta-value">{{ state.meta.faces?.toLocaleString() }}</div>
                <div class="meta-label">面片</div>
              </div>
              <div class="meta-item">
                <div class="meta-value">{{ state.meta.total_time }}s</div>
                <div class="meta-label">耗时</div>
              </div>
              <div class="meta-item">
                <div class="meta-value">{{ state.meta.vram_peak_gb }}GB</div>
                <div class="meta-label">显存峰值</div>
              </div>
            </div>
          </div>

          <div class="recon-right">
            <div ref="viewerContainer" class="viewer-container"></div>
            <div v-if="!state.glbUrl && state.stage !== 'done'" class="viewer-placeholder">
              <div class="placeholder-icon">🧊</div>
              <div class="placeholder-text">3D 重建结果将在此显示</div>
              <div class="placeholder-hint">旋转 · 缩放 · 平移</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.recon-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.recon-panel {
  width: 90vw;
  max-width: 1100px;
  height: 80vh;
  max-height: 700px;
  background: var(--bg-panel);
  border: var(--glass-border);
  border-radius: var(--radius);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}

.recon-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-bottom: var(--glass-border);
  background: rgba(0, 0, 0, 0.2);
}
.recon-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-bright);
  display: flex;
  align-items: center;
  gap: 8px;
}
.recon-icon { font-size: 20px; }
.recon-header-actions { display: flex; gap: 6px; }
.recon-btn-sm {
  font-size: 11px;
  padding: 4px 12px;
  border-radius: 6px;
  border: 1px solid var(--border-solid);
  background: var(--bg-card);
  color: var(--text);
  cursor: pointer;
  transition: all 0.15s;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
}
.recon-btn-sm:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.recon-btn-sm.download {
  border-color: var(--accent3);
  color: var(--accent3);
}
.recon-btn-sm.close:hover {
  border-color: var(--danger);
  color: var(--danger);
}

.recon-body {
  flex: 1;
  display: grid;
  grid-template-columns: 360px 1fr;
  overflow: hidden;
}

.recon-left {
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.upload-zone {
  border: 2px dashed var(--border-solid);
  border-radius: var(--radius-sm);
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
  min-height: 180px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.upload-zone:hover,
.upload-zone.dragover {
  border-color: var(--accent);
  background: rgba(0, 212, 255, 0.05);
}
.upload-zone.processing {
  cursor: default;
  border-style: solid;
  border-color: var(--border-solid);
}
.upload-icon { font-size: 36px; }
.upload-text {
  font-size: 14px;
  color: var(--text);
  font-weight: 500;
}
.upload-hint {
  font-size: 11px;
  color: var(--text-dim);
}

.processing-spinner {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 3px solid transparent;
  border-top-color: currentColor;
  animation: spin 0.8s linear infinite;
}
.processing-stage {
  font-size: 13px;
  font-weight: 600;
}
.processing-detail {
  font-size: 11px;
  color: var(--text-dim);
  max-width: 280px;
  text-align: center;
}

.progress-bar-container {
  position: relative;
  height: 24px;
  background: var(--bg-input);
  border-radius: 6px;
  overflow: hidden;
  border: 1px solid var(--border-solid);
}
.progress-bar {
  height: 100%;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  opacity: 0.8;
}
.progress-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 11px;
  font-weight: 700;
  color: var(--text-bright);
  text-shadow: 0 0 4px rgba(0, 0, 0, 0.8);
}

.preview-section { }
.preview-label {
  font-size: 11px;
  color: var(--text-dim);
  margin-bottom: 6px;
}
.preview-img {
  width: 100%;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-solid);
}

.error-box {
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: var(--radius-sm);
  padding: 12px;
}
.error-title {
  color: var(--danger);
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 4px;
}
.error-detail {
  font-size: 11px;
  color: var(--text-dim);
  white-space: pre-wrap;
  word-break: break-word;
}

.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.meta-item {
  background: var(--bg-card);
  border: var(--glass-border);
  border-radius: var(--radius-sm);
  padding: 10px;
  text-align: center;
}
.meta-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--accent);
}
.meta-label {
  font-size: 10px;
  color: var(--text-dim);
  margin-top: 2px;
}

.recon-right {
  position: relative;
  background: #060a13;
  border-left: var(--glass-border);
}
.viewer-container {
  width: 100%;
  height: 100%;
}
.viewer-container canvas {
  display: block;
}
.viewer-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  pointer-events: none;
}
.placeholder-icon { font-size: 48px; opacity: 0.3; }
.placeholder-text { font-size: 13px; color: var(--text-dim); }
.placeholder-hint { font-size: 10px; color: var(--text-dim); opacity: 0.6; }

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
