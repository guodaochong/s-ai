import { ref } from 'vue'
import type { ServiceStatus } from '@/types'
import { SERVICE_PORTS } from '@/types'

const services = ref<(ServiceStatus & { name: string })[]>([])
const serviceCount = ref({ healthy: 0, tools: 0 })

async function refresh() {
  try {
    const resp = await fetch('/api/servers')
    const data = await resp.json()
    const list: (ServiceStatus & { name: string })[] = []
    let healthy = 0
    let tools = 0
    for (const [name, info] of Object.entries(data) as [string, any][]) {
      const isHealthy = info.status === 'healthy'
      if (isHealthy) {
        healthy++
        tools += info.info?.tools?.length || 0
      }
      list.push({
        name,
        url: `http://127.0.0.1:${SERVICE_PORTS[name] || 3000}`,
        healthy: isHealthy,
        info: info.info,
      })
    }
    services.value = list
    serviceCount.value = { healthy, tools }
  } catch {
    services.value = []
    serviceCount.value = { healthy: 0, tools: 0 }
  }
}

export function useServices() {
  return { services, serviceCount, refresh }
}
