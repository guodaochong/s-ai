export interface SSEEvent {
  type: string
  [key: string]: any
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

export interface ToolResult {
  tool: string
  server: string
  result: Record<string, any>
  elapsed_ms?: number
}

export interface MapLayerInfo {
  id: string
  name: string
  visible: boolean
}

export interface ServiceStatus {
  name: string
  url: string
  healthy: boolean
  info?: Record<string, any>
}

export interface ThinkingLine {
  agent: string
  content: string
  type?: 'default' | 'step-header' | 'step-goal' | 'step-decision' | 'step-error' | 'step-ok'
}

export const SERVICE_PORTS: Record<string, number> = {
  router: 3000,
  gis: 5001,
  data: 5002,
  knowledge: 5003,
  map: 5004,
  hydro: 5005,
  flood: 5006,
  raster: 5007,
}

export const SERVICE_META: Record<string, { name: string; label: string; color: string }> = {
  router: { name: 'Router', label: '总指挥', color: '#00d4ff' },
  gis: { name: 'GIS', label: 'GIS专家', color: '#00ff88' },
  data: { name: 'Data', label: '数据管家', color: '#ffaa00' },
  knowledge: { name: 'Knowledge', label: '知识顾问', color: '#cc88ff' },
  map: { name: 'Map', label: '制图师', color: '#ff8800' },
  hydro: { name: 'Hydro', label: '水文建模师', color: '#00ccff' },
  flood: { name: 'Flood', label: '洪水分析师', color: '#ff4444' },
  raster: { name: 'Raster', label: '地形分析专家', color: '#44ff44' },
}
