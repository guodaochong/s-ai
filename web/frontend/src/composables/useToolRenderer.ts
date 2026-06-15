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

  reconstruct_3d(r, ms) {
    if (!r.recon_3d) return { html: '', mapActions: [] }
    const glbUrl = r.glb_url
    const v = (r.vertices || 0).toLocaleString()
    const f = (r.faces || 0).toLocaleString()
    const t = r.total_time || '?'
    const vram = r.vram_peak_gb || '?'
    const html = `
      <div class="tr-recon-card">
        <div class="tr-recon-header">🧊 AI 三维重建完成</div>
        <div class="tr-recon-stats">
          <div class="tr-recon-stat"><span class="tr-recon-num">${v}</span><span class="tr-recon-lbl">顶点</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num">${f}</span><span class="tr-recon-lbl">面片</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num">${t}s</span><span class="tr-recon-lbl">耗时</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num">${vram}GB</span><span class="tr-recon-lbl">显存</span></div>
        </div>
        <div class="tr-recon-actions">
          <a class="tr-recon-btn" href="${glbUrl}" download>⬇ 下载 GLB</a>
          <button class="tr-recon-btn primary" onclick="window.__openReconResult('${glbUrl}')">👁️ 查看 3D</button>
        </div>
      </div>`
    return { html, mapActions: [] }
  },

  precipitation_grid(r, ms) {
    if (!r.precipitation_grid) return { html: '', mapActions: [] }

    const actions: (() => void)[] = []
    const gridLats: number[] = r.grid_lats || []
    const gridLons: number[] = r.grid_lons || []
    const matrix: number[][] = r.precipitation_matrix || []
    const timeSteps: string[] = r.time_steps || []
    const stats = r.stats || {}
    const bbox = r.bbox || []
    const gs = r.grid_size || 8

    function precipColor(mm: number): { fill: string; stroke: string } {
      if (mm < 0.1) return { fill: 'rgba(30,40,60,0.1)', stroke: 'rgba(40,60,80,0.2)' }
      if (mm < 10) return { fill: 'rgba(169,239,147,0.75)', stroke: 'rgba(169,239,147,0.9)' }
      if (mm < 25) return { fill: 'rgba(63,184,60,0.85)', stroke: 'rgba(63,184,60,1)' }
      if (mm < 50) return { fill: 'rgba(97,184,255,0.75)', stroke: 'rgba(97,184,255,0.9)' }
      if (mm < 100) return { fill: 'rgba(0,1,247,0.65)', stroke: 'rgba(0,1,247,0.8)' }
      if (mm < 150) return { fill: 'rgba(252,0,251,0.65)', stroke: 'rgba(252,0,251,0.8)' }
      return { fill: 'rgba(255,0,0,1)', stroke: 'rgba(200,0,0,1)' }
    }

    function precipLabel(mm: number): string {
      if (mm < 0.1) return ''
      if (mm < 10) return '小雨'
      if (mm < 25) return '中雨'
      if (mm < 50) return '大雨'
      if (mm < 100) return '暴雨'
      if (mm < 150) return '大暴雨'
      return '特大暴雨'
    }

    actions.push(() => {
      const map = ms.getMap()
      if (!map) return

      const container = map.getContainer()
      const panel = container.closest('.map-panel') || container.parentElement

      ;(map as any)._precip_layers?.forEach((l: any) => map.removeLayer(l))
      if ((map as any)._precip_timer) clearInterval((map as any)._precip_timer)
      ;(panel as any)?.querySelector?.('#precip-timeline')?.remove?.()

      const layers: any[] = []
      let currentStep = 0
      let playing = true
      const totalSteps = matrix.length
      const cellLat = gridLats.length > gs ? Math.abs(gridLats[gs] - gridLats[0]) : (bbox.length >= 4 ? (bbox[3] - bbox[1]) / gs : 0.05)
      const cellLon = gridLons.length > 1 ? Math.abs(gridLons[1] - gridLons[0]) : (bbox.length >= 4 ? (bbox[2] - bbox[0]) / gs : 0.05)
      const halfLat = cellLat / 2
      const halfLon = cellLon / 2

      function renderStep(step: number) {
        layers.forEach(l => map.removeLayer(l))
        layers.length = 0
        const frame = matrix[step] || []
        const zoom = map.getZoom()
        const showValues = zoom >= 10

        const layerGroup = L.layerGroup()
        frame.forEach((val, idx) => {
          if (idx >= gridLats.length) return
          const lat = gridLats[idx]
          const lon = gridLons[idx]
          const colors = precipColor(val)
          const bounds: L.LatLngBounds = L.latLngBounds(
            [lat - halfLat, lon - halfLon],
            [lat + halfLat, lon + halfLon],
          )
          const rect = L.rectangle(bounds, {
            fillColor: colors.fill,
            color: colors.stroke,
            weight: 0.5,
            fillOpacity: 1,
          })
          if (val >= 0.1) {
            rect.bindTooltip(`${val.toFixed(1)}mm/h ${precipLabel(val)}`, {
              sticky: true, className: 'precip-tip', direction: 'center',
            })
            if (showValues && val >= 1) {
              rect.bindTooltip(`${val.toFixed(1)}`, {
                permanent: true, className: 'precip-val', direction: 'center',
              })
            }
          }
          layerGroup.addLayer(rect)
          layers.push(rect)
        })
        layerGroup.addTo(map)

        const sc: any[] = r.storm_centers || []
        const scInfo = sc.find((s: any) => s.time === timeSteps[step]) || sc[step]
        if (scInfo) {
          const sm = L.circleMarker([scInfo.lat, scInfo.lon], {
            radius: 10, fillColor: '#ff0000', color: '#fff', weight: 3, fillOpacity: 0.95,
          })
          const place = scInfo.place || ''
          sm.bindPopup(
            `<div style="font-size:12px;line-height:1.5">
               <b style="color:#ff0000">🌧️ 暴雨中心</b><br/>
               <b>强度:</b> ${scInfo.mm.toFixed(1)}mm/h ${precipLabel(scInfo.mm)}<br/>
               <b>时间:</b> ${(scInfo.time || '').replace('T', ' ').slice(0, 16)}<br/>
               ${place ? `<b>位置:</b> ${place}` : `<b>坐标:</b> ${scInfo.lat}, ${scInfo.lon}`}
             </div>`
          )
          sm.addTo(map)
          layers.push(sm)
        }

        updateTimelineUI(step)
      }

      function updateTimelineUI(step: number) {
        const playBtn = panel?.querySelector('#precip-play') as HTMLButtonElement
        const timeLabel = panel?.querySelector('#precip-cur-time') as HTMLElement
        const slider = panel?.querySelector('#precip-slider') as HTMLInputElement
        const stepInfo = panel?.querySelector('#precip-step-info') as HTMLElement
        const sc2: any[] = r.storm_centers || []
        const scInfo2 = sc2.find((s: any) => s.time === timeSteps[step]) || sc2[step]
        if (timeLabel) {
          const t = timeSteps[step] || ''
          const d = t.slice(0, 10)
          const h = t.slice(11, 16)
          const place = scInfo2?.place || ''
          timeLabel.textContent = place ? `${d} ${h} · 📍${place}` : `${d} ${h}`
        }
        if (playBtn) playBtn.textContent = playing ? '⏸' : '▶'
        if (slider) slider.value = String(step)
        if (stepInfo) stepInfo.textContent = `${step + 1} / ${totalSteps}`
      }

      renderStep(0)

      if (playing) {
        (map as any)._precip_timer = setInterval(() => {
          currentStep = (currentStep + 1) % totalSteps
          renderStep(currentStep)
        }, 700)
      }

      ;(map as any)._precip_layers = layers

      const tl = document.createElement('div')
      tl.id = 'precip-timeline'
      tl.className = 'precip-timeline'
      tl.innerHTML = `
        <div class="ptl-bar">
          <button id="ptl-prev" class="ptl-btn" title="上一帧">⏮</button>
          <button id="precip-play" class="ptl-btn ptl-play" title="播放/暂停">⏸</button>
          <button id="ptl-next" class="ptl-btn" title="下一帧">⏭</button>
          <span id="precip-cur-time" class="ptl-time">--</span>
          <input id="precip-slider" type="range" min="0" max="${totalSteps - 1}" value="0" class="ptl-slider" />
          <span id="precip-step-info" class="ptl-step">1 / ${totalSteps}</span>
        </div>
        <div class="ptl-legend">
          <span class="ptl-lg"><span class="ptl-swatch" style="background:rgba(169,239,147,0.75)"></span>0.1-10</span>
          <span class="ptl-lg"><span class="ptl-swatch" style="background:rgba(63,184,60,0.85)"></span>10-25</span>
          <span class="ptl-lg"><span class="ptl-swatch" style="background:rgba(97,184,255,0.75)"></span>25-50</span>
          <span class="ptl-lg"><span class="ptl-swatch" style="background:rgba(0,1,247,0.65)"></span>50-100</span>
          <span class="ptl-lg"><span class="ptl-swatch" style="background:rgba(252,0,251,0.65)"></span>100-150</span>
          <span class="ptl-lg"><span class="ptl-swatch" style="background:rgba(255,0,0,1)"></span>>150</span>
          <span class="ptl-lg-unit">mm/h</span>
        </div>
      `
      panel?.appendChild(tl)

      tl.querySelector('#precip-play')?.addEventListener('click', () => {
        playing = !playing
        if (playing) {
          ;(map as any)._precip_timer = setInterval(() => {
            currentStep = (currentStep + 1) % totalSteps
            renderStep(currentStep)
          }, 700)
        } else {
          if ((map as any)._precip_timer) clearInterval((map as any)._precip_timer)
        }
        updateTimelineUI(currentStep)
      })
      tl.querySelector('#ptl-prev')?.addEventListener('click', () => {
        currentStep = (currentStep - 1 + totalSteps) % totalSteps
        renderStep(currentStep)
      })
      tl.querySelector('#ptl-next')?.addEventListener('click', () => {
        currentStep = (currentStep + 1) % totalSteps
        renderStep(currentStep)
      })
      tl.querySelector('#precip-slider')?.addEventListener('input', (e) => {
        currentStep = parseInt((e.target as HTMLInputElement).value)
        renderStep(currentStep)
      })

      map.on('zoomend', () => renderStep(currentStep))

      if (bbox.length >= 4) {
        ms.fitBounds([[bbox[1], bbox[0]], [bbox[3], bbox[2]]])
      }
    })

    const series = r.area_average_series || []
    const maxAvg = Math.max(...series.map((s: any) => s.value_mm || 0), 0.1)
    const bw = 370 / Math.max(series.length, 1)
    let bars = ''
    series.forEach((s: any, i: number) => {
      const h = (s.value_mm || 0) / maxAvg * 80
      const x = i * bw + 15
      const color = h > 60 ? '#ff4400' : h > 30 ? '#ffaa00' : h > 5 ? '#3fb83c' : '#1a3a5a'
      bars += `<rect x="${x}" y="${90 - h}" width="${Math.max(bw - 1, 1)}" height="${h}" fill="${color}" opacity=".75"/>`
    })
    const hydrograph = `<svg viewBox="0 0 400 110" class="tr-chart">${bars}<line x1="15" y1="90" x2="385" y2="90" stroke="#334" stroke-width="0.5"/><text x="15" y="10" fill="#667" font-size="9">面雨量过程线 (mm/h)</text></svg>`

    const s = stats
    const html = `
      <div class="tr-recon-card" style="border-color:rgba(0,180,255,.25);background:rgba(0,140,255,.05)">
        <div class="tr-recon-header" style="color:#00b4ff">🌧️ 气象网格降水分析</div>
        <div style="font-size:10px;color:#64748b;margin-bottom:8px">${r.date_start || '?'} ~ ${r.date_end || '?'} | ${gs}×${gs}网格 | ${timeSteps.length}h</div>
        <div class="tr-recon-stats">
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#ff6600">${(s.max_mm || 0).toFixed(1)}</span><span class="tr-recon-lbl">最大mm</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#00ccff">${(s.mean_mm || 0).toFixed(2)}</span><span class="tr-recon-lbl">平均mm</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#00ff88">${(s.total_area_avg_mm || 0).toFixed(1)}</span><span class="tr-recon-lbl">累计mm</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#ffaa00">${(s.peak_intensity_mm_hr || 0).toFixed(1)}</span><span class="tr-recon-lbl">峰值mm/h</span></div>
        </div>
        <div class="tr-sub" style="margin:6px 0">📍 暴雨中心: ${(s.peak_center?.lat || 0).toFixed(3)}, ${(s.peak_center?.lon || 0).toFixed(3)}</div>
        ${hydrograph}
        <div class="tr-sub" style="margin-top:4px">🎨 网格动画+时间轴已加载到地图下方</div>
      </div>`
    return { html, mapActions: actions }
  },

  building_extract(r, ms) {
    if (!r.building_extract) return { html: '', mapActions: [] }

    const actions: (() => void)[] = []
    const buildings = r.buildings || []
    const count = r.count || buildings.length
    const avgH = r.avg_height_m || 0
    const totalA = r.total_area_m2 || 0
    const bbox = r.bbox || []

    function heightColor(h: number): { fill: string; stroke: string } {
      if (h <= 3) return { fill: 'rgba(74,222,128,0.45)', stroke: '#4ade80' }
      if (h <= 6) return { fill: 'rgba(34,211,238,0.45)', stroke: '#22d3ee' }
      if (h <= 9) return { fill: 'rgba(96,165,250,0.45)', stroke: '#60a5fa' }
      if (h <= 12) return { fill: 'rgba(167,139,250,0.45)', stroke: '#a78bfa' }
      if (h <= 15) return { fill: 'rgba(244,114,182,0.45)', stroke: '#f472b6' }
      if (h <= 20) return { fill: 'rgba(251,146,60,0.45)', stroke: '#fb923c' }
      return { fill: 'rgba(239,68,68,0.5)', stroke: '#ef4444' }
    }

    actions.push(() => {
      const map = ms.getMap()
      if (!map) return

      ;(map as any)._building_layer?.forEach((l: any) => map.removeLayer(l))
      if ((map as any)._sat_layer) {
        map.removeLayer((map as any)._sat_layer)
        map.eachLayer((layer: any) => {
          if (layer instanceof L.TileLayer) {
            layer.setOpacity(layer._orig_opacity ?? 1)
          }
        })
        ;(map as any)._sat_layer = null
      }
      const container = map.getContainer()
      const panel = container.closest('.map-panel') || container.parentElement
      ;(panel as any)?.querySelector?.('#building-stats-panel')?.remove?.()

      const satLayer = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { maxZoom: 19, attribution: 'ArcGIS World Imagery', className: 'sat-base-layer' }
      )
      satLayer.addTo(map)
      satLayer.bringToBack()
      ;(map as any)._sat_layer = satLayer

      map.eachLayer((layer: any) => {
        if (layer instanceof L.TileLayer && layer !== satLayer) {
          layer._orig_opacity = layer.options.opacity ?? 1
          layer.setOpacity(0)
        }
      })

      const layers: any[] = []

      buildings.forEach((f: any, idx: number) => {
        const coords = f.geometry?.coordinates?.[0]
        if (!coords || coords.length < 3) return

        const h = f.properties?.height_m || 5
        const c = heightColor(h)
        const latlngs = coords.map((co: number[]) => [co[1], co[0]] as [number, number])

        const tColor = f.properties?.type_color || c.stroke
        const tIcon = f.properties?.type_icon || '🏢'
        const tName = f.properties?.building_type || '建筑'

        const polygon = L.polygon(latlngs, {
          color: tColor,
          weight: 1.5,
          opacity: 0.9,
          fillColor: tColor,
          fillOpacity: 0.4,
        })

        const area = f.properties?.area_m2 || 0
        const w = f.properties?.width_m || 0
        const l2 = f.properties?.length_m || 0
        const conf = f.properties?.confidence || 0

        polygon.bindPopup(
          `<div style="font-size:12px;line-height:1.6">
             <b style="color:${tColor}">${tIcon} ${tName} #${idx + 1}</b><br/>
             <b>估算高度:</b> ${h}m<br/>
             <b>占地面积:</b> ${area.toFixed(1)} m²<br/>
             <b>尺寸:</b> ${w.toFixed(1)}m × ${l2.toFixed(1)}m<br/>
             <b>置信度:</b> ${(conf * 100).toFixed(0)}%
           </div>`
        )

        polygon.addTo(map)
        layers.push(polygon)
      })

      ;(map as any)._building_layer = layers

      if (layers.length > 0) {
        const group = L.featureGroup(layers)
        map.fitBounds(group.getBounds(), { padding: [50, 50] })
      }

      _injectBuildingCss()
      if (panel) {
        const statsDiv = document.createElement('div')
        statsDiv.id = 'building-stats-panel'
        statsDiv.className = 'building-stats-panel'
        statsDiv.innerHTML = `
          <div class="bsp-header">
            <span class="bsp-icon">🏗️</span>
            <span class="bsp-title">AI建筑提取结果</span>
            <button class="bsp-close" onclick="this.parentElement.parentElement.remove()">✕</button>
          </div>
          <div class="bsp-body">
            <div class="bsp-stat"><div class="bsp-val" style="color:#00ff88">${count}</div><div class="bsp-lbl">建筑数量</div></div>
            <div class="bsp-stat"><div class="bsp-val" style="color:#00d4ff">${avgH.toFixed(1)}<span class="bsp-unit">m</span></div><div class="bsp-lbl">平均高度</div></div>
            <div class="bsp-stat"><div class="bsp-val" style="color:#ffaa00">${(totalA / 10000).toFixed(2)}<span class="bsp-unit">ha</span></div><div class="bsp-lbl">总占地</div></div>
          </div>
          <div class="bsp-legend">
            <div class="bsp-lg-title">建筑类型分类</div>
            <div class="bsp-lg-items">
              <div class="bsp-lg-item"><span class="bsp-swatch" style="background:#4ade80"></span>🏠 低层住宅</div>
              <div class="bsp-lg-item"><span class="bsp-swatch" style="background:#60a5fa"></span>🏢 高层住宅</div>
              <div class="bsp-lg-item"><span class="bsp-swatch" style="background:#22d3ee"></span>🏬 商业办公</div>
              <div class="bsp-lg-item"><span class="bsp-swatch" style="background:#f59e0b"></span>🏭 工业仓储</div>
              <div class="bsp-lg-item"><span class="bsp-swatch" style="background:#a78bfa"></span>🏫 公共设施</div>
              <div class="bsp-lg-item"><span class="bsp-swatch" style="background:#94a3b8"></span>🔧 附属设施</div>
            </div>
          </div>
          <div class="bsp-source">📡 ${r.data_source || 'ArcGIS + SAM vit_b'} · Zoom ${r.zoom || '?'} · ${r.n_tiles || '?'} tiles</div>
          <div class="bsp-toggle-row">
            <button class="bsp-toggle-btn" id="bsp-sat-toggle">🛰️ 卫星影像: 开</button>
          </div>
        `
        panel.appendChild(statsDiv)

        const toggleBtn = statsDiv.querySelector('#bsp-sat-toggle')
        if (toggleBtn) {
          toggleBtn.addEventListener('click', () => {
            const m = ms.getMap()
            if (!m) return
            const sat = (m as any)._sat_layer
            if (!sat) return
            if (m.hasLayer(sat)) {
              m.removeLayer(sat)
              m.eachLayer((layer: any) => {
                if (layer instanceof L.TileLayer && layer !== sat) {
                  layer.setOpacity(layer._orig_opacity ?? 1)
                }
              })
              toggleBtn.textContent = '🛰️ 卫星影像: 关'
            } else {
              m.addLayer(sat)
              sat.bringToBack()
              m.eachLayer((layer: any) => {
                if (layer instanceof L.TileLayer && layer !== sat) {
                  layer.setOpacity(0)
                }
              })
              toggleBtn.textContent = '🛰️ 卫星影像: 开'
            }
          })
        }
      }
    })

    const html = `
      <div class="tr-recon-card">
        <div class="tr-recon-header" style="color:#00ff88">🏗️ AI建筑提取完成</div>
        <div style="font-size:10px;color:#64748b;margin-bottom:8px">
          ${r.data_source || 'ArcGIS World Imagery + SAM vit_b'} | Zoom ${r.zoom || '?'} | ${r.n_tiles || '?'} tiles
        </div>
        <div class="tr-recon-stats">
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#00ff88">${count}</span><span class="tr-recon-lbl">建筑数</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#00d4ff">${avgH.toFixed(1)}m</span><span class="tr-recon-lbl">平均高</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#ffaa00">${(totalA / 10000).toFixed(2)}ha</span><span class="tr-recon-lbl">总占地</span></div>
        </div>
        <div class="tr-sub" style="margin-top:4px">📍 ${count}栋建筑已渲染到地图，点击建筑查看详情</div>
      </div>`
    return { html, mapActions: actions }
  },

  water_monitor(r, ms) {
    if (!r.water_monitor) return { html: '', mapActions: [] }

    const actions: (() => void)[] = []
    const bodies = r.water_bodies || []
    const count = r.water_body_count || bodies.length
    const totalArea = r.total_water_area_km2 || 0
    const coverage = r.water_coverage_pct || 0
    const date = r.date || '?'
    const cloud = r.cloud_cover || 0
    const ndwiRange = r.ndwi_range || [0, 0]

    actions.push(() => {
      const map = ms.getMap()
      if (!map) return

      ;(map as any)._water_layer?.forEach((l: any) => map.removeLayer(l))
      const container = map.getContainer()
      const panel = container.closest('.map-panel') || container.parentElement
      ;(panel as any)?.querySelector?.('#water-stats-panel')?.remove?.()

      const layers: any[] = []

      bodies.forEach((f: any, idx: number) => {
        const coords = f.geometry?.coordinates?.[0]
        if (!coords || coords.length < 3) return
        const latlngs = coords.map((c: number[]) => [c[1], c[0]] as [number, number])
        const area = f.properties?.area_m2 || 0
        const ndwi = f.properties?.ndwi_mean || 0

        const polygon = L.polygon(latlngs, {
          color: '#00aaff',
          weight: 2,
          opacity: 0.9,
          fillColor: '#0066cc',
          fillOpacity: 0.6,
        })

        polygon.bindPopup(
          `<div style="font-size:12px;line-height:1.6">
             <b style="color:#00aaff">水体 #${idx + 1}</b><br/>
             <b>面积:</b> ${(area / 10000).toFixed(2)} ha<br/>
             <b>NDWI均值:</b> ${ndwi.toFixed(3)}<br/>
             <b>中心:</b> ${f.properties?.center?.[1]?.toFixed(4)}, ${f.properties?.center?.[0]?.toFixed(4)}
           </div>`
        )

        polygon.addTo(map)
        layers.push(polygon)
      })

      ;(map as any)._water_layer = layers

      if (layers.length > 0) {
        const group = L.featureGroup(layers)
        map.fitBounds(group.getBounds(), { padding: [50, 50] })
      } else if (r.bbox) {
        const b = r.bbox
        map.fitBounds([[b[1], b[0]], [b[3], b[2]]], { padding: [50, 50] })
      }

      _injectBuildingCss()
      if (panel) {
        const statsDiv = document.createElement('div')
        statsDiv.id = 'water-stats-panel'
        statsDiv.className = 'building-stats-panel'
        statsDiv.innerHTML = `
          <div class="bsp-header" style="background:rgba(0,170,255,0.06);border-color:rgba(0,170,255,0.1)">
            <span class="bsp-icon">🌊</span>
            <span class="bsp-title" style="color:#00aaff">遥感水体监测</span>
            <button class="bsp-close" onclick="this.parentElement.parentElement.remove()">✕</button>
          </div>
          <div class="bsp-body">
            <div class="bsp-stat"><div class="bsp-val" style="color:#00aaff">${count}</div><div class="bsp-lbl">水体数</div></div>
            <div class="bsp-stat"><div class="bsp-val" style="color:#00d4ff">${totalArea.toFixed(3)}<span class="bsp-unit">km²</span></div><div class="bsp-lbl">水面面积</div></div>
            <div class="bsp-stat"><div class="bsp-val" style="color:#4ade80">${coverage.toFixed(1)}<span class="bsp-unit">%</span></div><div class="bsp-lbl">覆盖率</div></div>
          </div>
          <div class="bsp-source" style="border-color:rgba(0,170,255,0.06)">
            📡 Sentinel-2 L2A 10m<br/>
            📅 ${date} · 云量${cloud}%<br/>
            📊 NDWI: [${ndwiRange[0]}, ${ndwiRange[1]}]
          </div>
        `
        panel.appendChild(statsDiv)
      }
    })

    const html = `
      <div class="tr-recon-card">
        <div class="tr-recon-header" style="color:#00aaff">🌊 遥感水体监测完成</div>
        <div style="font-size:10px;color:#64748b;margin-bottom:8px">
          Sentinel-2 L2A 10m | ${date} | 云量${cloud}%
        </div>
        <div class="tr-recon-stats">
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#00aaff">${count}</span><span class="tr-recon-lbl">水体数</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#00d4ff">${totalArea.toFixed(3)}km²</span><span class="tr-recon-lbl">水面面积</span></div>
          <div class="tr-recon-stat"><span class="tr-recon-num" style="color:#4ade80">${coverage.toFixed(1)}%</span><span class="tr-recon-lbl">覆盖率</span></div>
        </div>
        <div class="tr-sub" style="margin-top:4px">📍 ${count}处水体已渲染到地图，点击查看详情</div>
      </div>`
    return { html, mapActions: actions }
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

/* ── Precipitation timeline + legend styles (injected once) ── */
let _precipCssInjected = false
function _injectPrecipCss() {
  if (_precipCssInjected) return
  _precipCssInjected = true
  const style = document.createElement('style')
  style.textContent = `
.precip-timeline {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  background: rgba(8, 14, 28, 0.92);
  backdrop-filter: blur(16px);
  border-top: 1px solid rgba(0, 212, 255, 0.15);
  padding: 8px 16px;
}
.precip-timeline .ptl-bar {
  display: flex;
  align-items: center;
  gap: 10px;
}
.precip-timeline .ptl-btn {
  width: 34px;
  height: 34px;
  border-radius: 8px;
  border: 1px solid rgba(0, 212, 255, 0.2);
  background: rgba(0, 212, 255, 0.06);
  color: #00d4ff;
  font-size: 14px;
  cursor: pointer;
  display: grid;
  place-items: center;
  transition: all 0.15s;
}
.precip-timeline .ptl-btn:hover {
  background: rgba(0, 212, 255, 0.15);
  border-color: rgba(0, 212, 255, 0.4);
}
.precip-timeline .ptl-play {
  width: 40px;
  height: 40px;
  font-size: 16px;
  border-color: rgba(0, 212, 255, 0.4);
  background: rgba(0, 212, 255, 0.1);
}
.precip-timeline .ptl-time {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  font-family: 'JetBrains Mono', monospace;
  min-width: 120px;
  text-align: center;
  text-shadow: 0 0 8px rgba(0, 212, 255, 0.2);
}
.precip-timeline .ptl-slider {
  flex: 1;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: rgba(0, 212, 255, 0.1);
  border-radius: 3px;
  outline: none;
  cursor: pointer;
}
.precip-timeline .ptl-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #00d4ff;
  box-shadow: 0 0 8px rgba(0, 212, 255, 0.5);
  cursor: pointer;
}
.precip-timeline .ptl-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #00d4ff;
  border: none;
  box-shadow: 0 0 8px rgba(0, 212, 255, 0.5);
  cursor: pointer;
}
.precip-timeline .ptl-step {
  font-size: 11px;
  color: #64748b;
  font-family: 'JetBrains Mono', monospace;
  min-width: 50px;
  text-align: right;
}
.precip-timeline .ptl-legend {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}
.precip-timeline .ptl-lg {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  color: #94a3b8;
  font-family: 'JetBrains Mono', monospace;
}
.precip-timeline .ptl-swatch {
  width: 16px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.precip-timeline .ptl-lg-unit {
  font-size: 10px;
  color: #64748b;
  margin-left: auto;
}
.precip-val {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
  font-size: 10px !important;
  font-weight: 700;
  color: #fff;
  text-shadow: 0 0 4px rgba(0, 0, 0, 0.8);
  font-family: 'JetBrains Mono', monospace;
}
.precip-tip {
  background: rgba(10, 14, 26, 0.95);
  border: 1px solid rgba(0, 212, 255, 0.2);
  color: #e2e8f0;
  font-size: 11px;
  padding: 4px 8px;
  border-radius: 6px;
}
`
  document.head.appendChild(style)
}
_injectPrecipCss()

let _buildingCssInjected = false
function _injectBuildingCss() {
  if (_buildingCssInjected) return
  _buildingCssInjected = true
  const style = document.createElement('style')
  style.textContent = `
.building-stats-panel {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 1000;
  width: 280px;
  background: rgba(8, 14, 28, 0.92);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(0, 255, 136, 0.15);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
.building-stats-panel .bsp-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(0, 255, 136, 0.06);
  border-bottom: 1px solid rgba(0, 255, 136, 0.1);
}
.building-stats-panel .bsp-icon { font-size: 16px; }
.building-stats-panel .bsp-title {
  font-size: 13px;
  font-weight: 700;
  color: #00ff88;
  flex: 1;
}
.building-stats-panel .bsp-close {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: none;
  background: rgba(255,255,255,0.05);
  color: #94a3b8;
  cursor: pointer;
  font-size: 12px;
  display: grid;
  place-items: center;
  transition: all 0.15s;
}
.building-stats-panel .bsp-close:hover {
  background: rgba(239,68,68,0.15);
  color: #ef4444;
}
.building-stats-panel .bsp-body {
  display: flex;
  gap: 1px;
  padding: 0;
  background: rgba(255,255,255,0.03);
}
.building-stats-panel .bsp-stat {
  flex: 1;
  text-align: center;
  padding: 12px 4px;
  background: rgba(8,14,28,0.6);
}
.building-stats-panel .bsp-val {
  font-size: 22px;
  font-weight: 800;
  font-family: 'JetBrains Mono', monospace;
  line-height: 1.2;
}
.building-stats-panel .bsp-unit {
  font-size: 12px;
  font-weight: 400;
  opacity: 0.6;
}
.building-stats-panel .bsp-lbl {
  font-size: 10px;
  color: #64748b;
  margin-top: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.building-stats-panel .bsp-legend {
  padding: 10px 14px;
  border-top: 1px solid rgba(255,255,255,0.04);
}
.building-stats-panel .bsp-lg-title {
  font-size: 10px;
  color: #64748b;
  margin-bottom: 6px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.building-stats-panel .bsp-lg-items {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.building-stats-panel .bsp-lg-item {
  display: flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  color: #94a3b8;
  font-family: 'JetBrains Mono', monospace;
}
.building-stats-panel .bsp-swatch {
  width: 14px;
  height: 10px;
  border-radius: 2px;
  display: inline-block;
}
.building-stats-panel .bsp-source {
  font-size: 9px;
  color: #475569;
  padding: 6px 14px;
  border-top: 1px solid rgba(255,255,255,0.04);
  font-family: 'JetBrains Mono', monospace;
}
.building-stats-panel .bsp-toggle-row {
  padding: 8px 14px;
  border-top: 1px solid rgba(255,255,255,0.04);
}
.building-stats-panel .bsp-toggle-btn {
  width: 100%;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid rgba(0, 212, 255, 0.2);
  background: rgba(0, 212, 255, 0.06);
  color: #00d4ff;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}
.building-stats-panel .bsp-toggle-btn:hover {
  background: rgba(0, 212, 255, 0.15);
  border-color: rgba(0, 212, 255, 0.4);
}
.sat-base-layer {
  filter: brightness(0.7) contrast(1.1);
}
`
  document.head.appendChild(style)
}

