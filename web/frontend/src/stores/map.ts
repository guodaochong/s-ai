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

  return { layers, setMap, getMap, addLayer, addGeoJSON, addPoints, removeLayerById, fitBounds, clearAll }
})
