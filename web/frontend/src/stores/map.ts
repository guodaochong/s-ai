import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { MapLayerInfo } from '@/types'
import L from 'leaflet'

export const useMapStore = defineStore('map', () => {
  const layers = ref<MapLayerInfo[]>([])
  const layerMap = new Map<string, L.Layer>()
  let mapInstance: L.Map | null = null

  function setMap(map: L.Map) {
    mapInstance = map
  }

  function getMap(): L.Map | null {
    return mapInstance
  }

  function addLayer(layer: L.Layer, name: string) {
    if (!mapInstance) return
    layer.addTo(mapInstance)
    const id = `layer_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
    layerMap.set(id, layer)
    layers.value.push({ id, name, visible: true })
    return id
  }

  function fitBounds(bounds: L.LatLngBoundsExpression, padding = 0.2) {
    if (!mapInstance) return
    try {
      mapInstance.fitBounds(bounds, { padding: [padding * 100, padding * 100] })
    } catch {}
  }

  function addGeoJSON(geojson: any, options?: L.GeoJSONOptions, name = 'GeoJSON') {
    const defaultStyle = { color: '#00d4ff', fillColor: '#00d4ff', fillOpacity: 0.25, weight: 2 }
    const layer = L.geoJSON(geojson, { style: defaultStyle, ...options })
    const id = addLayer(layer, name)
    try {
      fitBounds(layer.getBounds().pad(0.2))
    } catch {}
    return { layer, id }
  }

  function addPoints(points: { lat: number; lng: number; label?: string }[], name = 'Points') {
    const markers: L.CircleMarker[] = []
    const bounds: L.LatLngTuple[] = []
    points.forEach(p => {
      if (p.lat && p.lng) {
        const mk = L.circleMarker([p.lat, p.lng], {
          radius: 6, fillColor: '#00ff88', color: '#00ff88', fillOpacity: 0.8,
        })
        if (p.label) mk.bindPopup(String(p.label))
        markers.push(mk)
        bounds.push([p.lat, p.lng])
      }
    })
    const group = L.layerGroup(markers)
    addLayer(group, name)
    if (bounds.length > 1) fitBounds(bounds)
    return bounds.length
  }

  function removeLayerById(id: string) {
    if (mapInstance) {
      const layer = layerMap.get(id)
      if (layer) {
        mapInstance.removeLayer(layer)
        layerMap.delete(id)
      }
    }
    layers.value = layers.value.filter(l => l.id !== id)
  }

  function clearAll() {
    if (mapInstance) {
      layerMap.forEach(layer => { mapInstance!.removeLayer(layer) })
    }
    layerMap.clear()
    layers.value = []
  }

  const cotLayerIds: string[] = []

  function clearCoTLayers() {
    cotLayerIds.forEach(id => removeLayerById(id))
    cotLayerIds.length = 0
  }

  function addCoTAction(action: any) {
    if (!mapInstance) return
    const type = action?.type
    const p = action?.params || {}
    clearCoTLayers()

    if (type === 'highlight_region' && p.bbox) {
      const [w, s, e, n] = p.bbox
      const color = p.color || '#00d4ff'
      const rect = L.rectangle([[s, w], [n, e]], {
        color, fillColor: color, fillOpacity: p.opacity || 0.2, weight: 2,
      })
      if (p.label) rect.bindPopup(p.label)
      const id = addLayer(rect, p.label || '高亮区域')
      cotLayerIds.push(id)
      fitBounds([[s, w], [n, e]], 0.3)
    }
    else if (type === 'flow_arrows' && p.arrows) {
      p.arrows.forEach((a: any) => {
        if (a.from && a.to) {
          const line = L.polyline([a.from, a.to], {
            color: p.color || '#fbbf24', weight: 3, dashArray: '10,8', opacity: 0.8,
          })
          const id = addLayer(line, '流向')
          cotLayerIds.push(id)
          if (a.to) {
            const arrow = L.circleMarker(a.to, {
              radius: 5, fillColor: p.color || '#fbbf24', color: p.color || '#fbbf24', fillOpacity: 1,
            })
            const id2 = addLayer(arrow, '流向端点')
            cotLayerIds.push(id2)
          }
        }
      })
    }
    else if (type === 'markers' && p.points) {
      p.points.forEach((pt: any) => {
        if (pt.coord) {
          const mk = L.circleMarker(pt.coord, {
            radius: 8, fillColor: pt.color || '#ef4444', color: pt.color || '#ef4444', fillOpacity: 0.8,
          })
          if (pt.label) mk.bindPopup(pt.label)
          const id = addLayer(mk, pt.label || '标记点')
          cotLayerIds.push(id)
        }
      })
    }
    else if (type === 'circle' && p.center) {
      const c = L.circle(p.center, {
        radius: (p.radius_km || 5) * 1000,
        color: p.color || '#f97316', fillColor: p.color || '#f97316', fillOpacity: 0.15, weight: 2,
      })
      if (p.label) c.bindPopup(p.label)
      const id = addLayer(c, p.label || '风险圈')
      cotLayerIds.push(id)
      fitBounds(c.getBounds(), 0.3)
    }
    else if (type === 'polygon' && p.coords) {
      const poly = L.polygon(p.coords, {
        color: p.color || '#22c55e', fillColor: p.color || '#22c55e', fillOpacity: 0.2, weight: 2,
      })
      if (p.label) poly.bindPopup(p.label)
      const id = addLayer(poly, p.label || '区域')
      cotLayerIds.push(id)
      fitBounds(poly.getBounds(), 0.3)
    }
  }

  return { layers, setMap, getMap, addLayer, addGeoJSON, addPoints, removeLayerById, fitBounds, clearAll, clearCoTLayers, addCoTAction }
})
