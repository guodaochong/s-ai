import { useMapStore } from '@/stores/map'
import { useThreeStore } from '@/stores/three'
import L from 'leaflet'

/**
 * Tool result renderer - strategy pattern per tool type.
 * Returns { html: string, mapActions: Function[] } so caller can apply map ops after render.
 */
export interface RenderOutput {
  html: string
  mapActions: (() => void)[]
}

export function useToolRenderer() {
  const mapStore = useMapStore()

  function render(tool: string, server: string, result: Record<string, any>): RenderOutput {
    if (!result) return { html: '', mapActions: [] }
    if (result.error) return { html: `<span class="tr-error">❌ ${esc(result.error)}</span>`, mapActions: [] }

    const strategy = STRATEGIES[tool]
    if (strategy) return strategy(result, mapStore)

    return renderGeneric(tool, server, result, mapStore)
  }

  return { render }
}

/* ── Per-tool strategies ── */

const STRATEGIES: Record<string, (r: any, ms: ReturnType<typeof useMapStore>) => RenderOutput> = {

  buffer(r, ms) {
    const actions: (() => void)[] = []
    if (r.geometry) {
      actions.push(() => {
        ms.addGeoJSON({ type: 'Feature', geometry: r.geometry, properties: { name: '缓冲区' } }, undefined, '缓冲区')
      })
    }
    return { html: '<span class="tr-accent">⭕ 缓冲区已自动绘制到地图</span>', mapActions: actions }
  },

  spatial_query(r, ms) {
    const actions: (() => void)[] = []
    if (r.geometry) {
      actions.push(() => ms.addGeoJSON({ type: 'Feature', geometry: r.geometry, properties: { name: '空间查询' } }, undefined, '空间查询'))
    }
    return { html: '<span class="tr-accent">📐 空间查询结果已绘制到地图</span>', mapActions: actions }
  },

  overlay(r, ms) {
    const actions: (() => void)[] = []
    if (r.geometry) {
      actions.push(() => ms.addGeoJSON({ type: 'Feature', geometry: r.geometry, properties: { name: '叠加分析' } }, { style: { color: '#ff8800', fillColor: '#ff8800', fillOpacity: 0.2, weight: 2 } }, '叠加分析'))
    }
    return { html: '<span class="tr-warn">📐 叠加分析结果已绘制到地图</span>', mapActions: actions }
  },

  geometry_properties(r, ms) {
    const actions: (() => void)[] = []
    if (r.bounds) {
      const b = r.bounds
      actions.push(() => ms.addGeoJSON({
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [[[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]], [b[0], b[1]]]] }
      }, { style: { color: '#00d4ff', fillOpacity: 0.08, weight: 1, dashArray: '5 5' } }, '几何属性'))
    }
    const area = typeof r.area_m2 === 'number' ? r.area_m2.toFixed(1) : '?'
    return { html: `<span class="tr-accent">📏 几何: ${r.geometry_type || '?'} 面积=${area}m²</span>`, mapActions: actions }
  },

  render_map(r) {
    if (r.image_base64) return { html: `<img src="data:image/png;base64,${r.image_base64}" style="max-width:100%;border-radius:6px" />`, mapActions: [] }
    return { html: '', mapActions: [] }
  },

  design_storm(r) {
    if (!r.rainfall_series) return { html: '', mapActions: [] }
    const pts = r.rainfall_series
    const maxI = Math.max(...pts.map((p: any) => p.intensity_mm_per_hr)) || 1
    const bw = 370 / pts.length
    let bars = ''
    pts.forEach((p: any, i: number) => {
      const h = p.intensity_mm_per_hr / maxI * 100
      const x = i * bw + 15
      const color = h > 70 ? '#ff4400' : h > 40 ? '#ff8800' : '#ffcc00'
      bars += `<rect x="${x}" y="${110 - h}" width="${bw - 1}" height="${h}" fill="${color}" opacity=".8"/>`
    })
    const svg = `<svg viewBox="0 0 400 140" class="tr-chart">${bars}<text x="15" y="10" fill="#667" font-size="9">${r.city || ''} P=${r.return_period_years || '?'}年</text><text x="15" y="130" fill="#667" font-size="9">${pts.length}时段</text></svg>`
    return { html: `<div class="tr-accent">🌧️ 设计暴雨: ${r.city || ''} P=${r.return_period_years || '?'}年</div>${svg}`, mapActions: [] }
  },

  runoff_compute(r) {
    const runoff = typeof r.runoff_mm === 'number' ? r.runoff_mm.toFixed(1) : '?'
    return { html: `<div class="tr-accent">💧 SCS-CN径流: 降雨=${r.rainfall_mm || '?'}mm 径流=${runoff}mm</div>`, mapActions: [] }
  },

  swmm_simulate(r) {
    if (!r.time_series) return { html: '', mapActions: [] }
    const ts = r.time_series
    const maxV = Math.max(...ts.map((t: any) => t.value)) || 1
    let d = ''
    ts.forEach((t: any, i: number) => {
      const x = i / (ts.length - 1) * 380 + 10
      const y = 130 - t.value / maxV * 120
      d += (i === 0 ? 'M' : 'L') + x + ' ' + y
    })
    const svg = `<svg viewBox="0 0 400 140" class="tr-chart"><path d="${d}" fill="none" stroke="#00ccff" stroke-width="2"/><text x="10" y="10" fill="#667" font-size="9">SWMM ${r.node_id || ''}</text></svg>`
    return { html: `<div class="tr-accent">🔧 SWMM模拟完成: ${r.node_id || ''}</div>${svg}`, mapActions: [] }
  },

  flood_inundation_map(r, ms) {
    const actions: (() => void)[] = []
    if (r.geojson) {
      actions.push(() => ms.addGeoJSON(r.geojson, { style: { color: '#ff4444', fillColor: '#ff4444', fillOpacity: 0.3, weight: 1 } }, '淹没分析'))
    }
    const area = typeof r.flooded_area_km2 === 'number' ? r.flooded_area_km2.toFixed(1) : '?'
    return { html: `<span class="tr-danger">🌊 淹没范围已绘制到地图 (${area}km²)</span>`, mapActions: actions }
  },

  flood_warning(r) {
    return { html: `<div class="tr-alert"><b>⚠️ 洪水预警</b><br><span class="tr-alert-text">${r.warning_level || ''} | ${r.message || ''}</span></div>`, mapActions: [] }
  },

  flood_risk_zones(r, ms) {
    const actions: (() => void)[] = []
    const colors: Record<string, string> = { high: '#ff4444', medium: '#ffaa00', low: '#00ff88' }
    if (r.zones) {
      r.zones.forEach((z: any) => {
        if (z.geometry) {
          const c = colors[z.risk] || '#888'
          actions.push(() => ms.addGeoJSON({ type: 'Feature', geometry: z.geometry }, { style: { color: c, fillColor: c, fillOpacity: 0.25, weight: 1 } }, `风险:${z.risk}`))
        }
      })
    }
    return { html: '<span class="tr-danger">🗺️ 风险分区已绘制</span>', mapActions: actions }
  },

  watershed_delineate(r, ms) {
    const actions: (() => void)[] = []
    if (r.boundary_geojson) {
      actions.push(() => ms.addGeoJSON(r.boundary_geojson, { style: { color: '#7c3aed', fillColor: '#7c3aed', fillOpacity: 0.15, weight: 2 } }, '流域边界'))
    }
    let info = '<span style="color:#7c3aed">🌊 流域已绘制到地图</span>'
    if (r.area_km2) info += `<div class="tr-sub">面积: ${r.area_km2.toFixed(1)}km²</div>`
    if (r.outlet) info += `<div class="tr-sub">出口: ${r.outlet.lat?.toFixed(4)}, ${r.outlet.lon?.toFixed(4)}</div>`
    return { html: info, mapActions: actions }
  },

  dem_analyze(r) {
    let info = '<div class="tr-accent">⛰️ DEM分析结果</div>'
    if (r.slope_mean != null) info += `<div class="tr-sub">平均坡度: ${r.slope_mean.toFixed(1)}° | 最大: ${(r.slope_max || 0).toFixed(1)}°</div>`
    if (r.elevation_range) info += `<div class="tr-sub">高程: ${r.elevation_range[0]}~${r.elevation_range[1]}m</div>`
    return { html: info, mapActions: [] }
  },

  flow_accumulation(r, ms) {
    const actions: (() => void)[] = []
    if (r.stream_geojson) {
      actions.push(() => ms.addGeoJSON(r.stream_geojson, { style: { color: '#00ccff', weight: 2, opacity: 0.8 } }, '河网'))
    }
    let info = '<div style="color:#00ccff">🏞️ 河网提取完成</div>'
    if (r.stream_count) info += `<div class="tr-sub">河流: ${r.stream_count}条 | 最高Strahler: ${r.max_strahler || '-'}</div>`
    return { html: info, mapActions: actions }
  },

  dem_render(r, ms) {
    const actions: (() => void)[] = []
    if (r.hillshade_image && r.bounds) {
      const b = r.bounds
      actions.push(() => {
        const map = ms.getMap()
        if (!map) return
        const bounds: L.LatLngTuple[] = [[b[1], b[0]], [b[3], b[2]]]
        const overlay = L.imageOverlay(`data:image/png;base64,${r.hillshade_image}`, bounds, { opacity: 0.7 })
        ms.addLayer(overlay, '山体阴影')
        ms.fitBounds(bounds)
      })
    }
    if (r.contour_geojson?.features) {
      r.contour_geojson.features.forEach((f: any) => {
        actions.push(() => ms.addGeoJSON(f, { style: { color: '#445566', weight: 0.8, opacity: 0.6, dashArray: '2,3' } }, '等高线'))
      })
    }
    let info = '<div class="tr-dim">🏔️ DEM地形渲染</div>'
    if (r.elevation_range) info += `<div class="tr-sub">高程: ${r.elevation_range[0]}~${r.elevation_range[1]}m</div>`
    return { html: info, mapActions: actions }
  },

  scatter_interpolate(r, ms) {
    const actions: (() => void)[] = []
    if (r.image_base64 && r.bounds) {
      const b = r.bounds
      actions.push(() => {
        const map = ms.getMap()
        if (!map) return
        const bounds: L.LatLngTuple[] = [[b[0], b[1]], [b[2], b[3]]]
        const overlay = L.imageOverlay(`data:image/png;base64,${r.image_base64}`, bounds, { opacity: 0.75 })
        ms.addLayer(overlay, '插值热力图')
        ms.fitBounds(bounds)
      })
      return {
        html: `<div class="tr-accent">🗺️ 插值热力图已叠加到地图</div><div class="tr-sub">${r.method || ''} | ${r.input_points || '?'}点 | ${r.valid_cells || '?'}有效格点</div><div class="tr-sub">范围: ${(r.z_min ?? 0).toFixed(1)}~${(r.z_max ?? 0).toFixed(1)}</div>`,
        mapActions: actions,
      }
    }
    let info = `<div class="tr-accent">📊 插值完成: ${r.method || ''}</div>`
    info += `<div class="tr-sub">输入: ${r.input_points || '?'}点 | 网格: ${r.grid_resolution || '?'}</div>`
    if (r.z_min != null) info += `<div class="tr-sub">值域: ${r.z_min.toFixed(2)} ~ ${r.z_max.toFixed(2)}</div>`
    if (r.tin_geojson) {
      actions.push(() => {
        const threeStore = useThreeStore()
        threeStore.buildTinMesh3D(r)
      })
    }
    return { html: info, mapActions: actions }
  },

  terrain_profile(r) {
    if (!r.profile) return { html: '', mapActions: [] }
    const pts = r.profile
    const maxE = Math.max(...pts.map((p: any) => p.elevation_m))
    const minE = Math.min(...pts.map((p: any) => p.elevation_m))
    const range = maxE - minE || 1
    let pathD = '', fillD = ''
    pts.forEach((p: any, i: number) => {
      const x = i / (pts.length - 1) * 380 + 10
      const y = 110 - ((p.elevation_m - minE) / range) * 90 - 5
      pathD += (i === 0 ? 'M' : 'L') + ' ' + x + ' ' + y
      fillD += (i === 0 ? `M ${x} 110 L ${x} ${y}` : ` L ${x} ${y}`)
    })
    fillD += ' L 390 110 Z'
    const gid = 'tg_' + Math.random().toString(36).slice(2, 8)
    const svg = `<svg viewBox="0 0 400 130" class="tr-chart"><path d="${fillD}" fill="url(#${gid})" opacity=".3"/><defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#00d4ff"/><stop offset="100%" stop-color="#0a0e1a"/></linearGradient></defs><path d="${pathD}" fill="none" stroke="#00d4ff" stroke-width="2"/><text x="10" y="12" fill="#667" font-size="9">${maxE}m</text></svg>`
    return { html: svg, mapActions: [] }
  },

  get_parameter(r) {
    if (!r.results) return { html: '', mapActions: [] }
    let h = `<div class="tr-card"><b class="tr-purple">📋 ${r.parameter || '查询结果'}</b>`
    r.results.slice(0, 8).forEach((e: any) => {
      h += `<div class="tr-sub">• ${e.surface || e.city || '?'}: ${e.n_typical || e.cn_amc2 || JSON.stringify(e).slice(0, 60)}</div>`
    })
    h += '</div>'
    return { html: h, mapActions: [] }
  },

  import_network(r, ms) {
    const actions: (() => void)[] = []
    if (r.geojson?.features) {
      actions.push(() => ms.addGeoJSON(r.geojson, { style: { color: '#00d4ff', weight: 3, opacity: 0.8 } }, '管网'))
    }
    return { html: `<span class="tr-accent">📁 管网导入: ${r.feature_count || 0}要素</span>`, mapActions: actions }
  },

  hydrodynamic_2d_sim(r) {
    const threeStore = useThreeStore()
    threeStore.loadHydroSimulation(r)
    return { html: `<span class="tr-accent">🌊 2D水动力模拟完成: ${r.frames?.length || 0}帧 | 峰值水深 ${r.peak_max_depth_m || '?'}m</span>`, mapActions: [] }
  },
}

/* ── Generic renderer (fallback) ── */

function renderGeneric(tool: string, server: string, result: Record<string, any>, mapStore: ReturnType<typeof useMapStore>): RenderOutput {
  const actions: (() => void)[] = []
  const parts: string[] = []

  if (result.image_base64) {
    parts.push(`<img src="data:image/png;base64,${result.image_base64}" style="max-width:100%;border-radius:6px;margin:4px 0" />`)
  }

  if (result.geojson || (result.coordinates && Array.isArray(result.coordinates))) {
    const gj = result.geojson || { type: 'Feature', geometry: { type: result.geometry_type || 'Polygon', coordinates: result.coordinates }, properties: { name: tool } }
    actions.push(() => mapStore.addGeoJSON(gj, undefined, tool))
    parts.push('<div class="tr-accent">🗺️ 已绘制到地图</div>')
  }

  if (result.points && Array.isArray(result.points) && result.points.length > 0) {
    actions.push(() => mapStore.addPoints(result.points, tool))
    parts.push(`<div style="color:#00ff88">📍 ${result.points.length}个点已标记到地图</div>`)
  }

  const tsData = result.time_series || result.data_points || result.series || result.values
  if (tsData && Array.isArray(tsData) && tsData.length > 2) {
    const vals = tsData.map((v: any) => typeof v === 'object' ? (v.value || v.y || v.z || v.elevation || 0) : v)
    const labels = tsData.map((v: any, i: number) => typeof v === 'object' ? (v.label || v.name || v.time || i) : i)
    const maxV = Math.max(...vals) || 1
    const minV = Math.min(...vals)
    const range = maxV - minV || 1
    const isBar = result.chart_type === 'bar' || tool.indexOf('rain') >= 0 || tool.indexOf('storm') >= 0

    let svgContent = ''
    for (let gi = 0; gi < 5; gi++) {
      const gy = 135 - gi * 26
      svgContent += `<line x1="35" y1="${gy}" x2="405" y2="${gy}" stroke="#1a2332" stroke-width="1"/>`
      svgContent += `<text x="32" y="${gy + 3}" fill="#445566" font-size="8" text-anchor="end">${(minV + gi * range / 4).toFixed(1)}</text>`
    }

    if (isBar) {
      const bw = 360 / tsData.length
      vals.forEach((v: number, i: number) => {
        const bh = Math.max(2, (v - minV) / range * 110)
        const bx = i * bw + 38
        const color = v > maxV * 0.7 ? '#ff4400' : v > maxV * 0.4 ? '#ffaa00' : '#00ccff'
        svgContent += `<rect x="${bx}" y="${135 - bh}" width="${Math.max(bw - 2, 2)}" height="${bh}" fill="${color}" opacity=".85" rx="1"/>`
      })
    } else {
      let pd = ''
      vals.forEach((v: number, i: number) => {
        const x = i / (vals.length - 1) * 370 + 35
        const y = 135 - ((v - minV) / range) * 110
        pd += (i === 0 ? 'M' : 'L') + x + ' ' + y
      })
      const fd = pd + ` L ${35 + 370} 135 L 35 135 Z`
      const agId = 'ag_' + Math.random().toString(36).slice(2, 8)
      svgContent += `<path d="${fd}" fill="url(#${agId})" opacity=".15"/><defs><linearGradient id="${agId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#00d4ff"/><stop offset="100%" stop-color="#0a0e1a"/></linearGradient></defs>`
      svgContent += `<path d="${pd}" fill="none" stroke="#00d4ff" stroke-width="2"/>`
      vals.forEach((v: number, i: number) => {
        if (i % Math.max(1, Math.floor(vals.length / 20)) === 0) {
          const x = i / (vals.length - 1) * 370 + 35
          const y = 135 - ((v - minV) / range) * 110
          svgContent += `<circle cx="${x}" cy="${y}" r="2" fill="#00d4ff"/>`
        }
      })
    }

    parts.push(`<svg viewBox="0 0 420 160" class="tr-chart">${svgContent}</svg>`)
  }

  if (result.table && Array.isArray(result.table) && result.table.length > 0) {
    let tbl = '<table class="tr-table"><tr>'
    const cols = Object.keys(result.table[0])
    cols.forEach(c => { tbl += `<th>${esc(c)}</th>` })
    tbl += '</tr>'
    result.table.slice(0, 15).forEach((row: any) => {
      tbl += '<tr>'
      cols.forEach(c => { tbl += `<td>${esc(String(row[c] ?? ''))}</td>` })
      tbl += '</tr>'
    })
    tbl += '</table>'
    parts.push(tbl)
  }

  if (result.code) {
    parts.push(`<details class="tr-details"><summary>生成代码 (${result.code.split('\n').length}行)</summary><pre class="tr-code">${esc(result.code)}</pre></details>`)
  }

  if (parts.length === 0) {
    let jsonStr = JSON.stringify(result, null, 2)
    if (jsonStr.length > 600) jsonStr = jsonStr.slice(0, 600) + '\n...'
    parts.push(`<pre class="tr-json">${esc(jsonStr)}</pre>`)
  }

  return { html: parts.join(''), mapActions: actions }
}

function esc(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}


