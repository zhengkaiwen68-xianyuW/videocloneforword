import { defineStore } from 'pinia'
import { ref } from 'vue'
import { configApi } from '../api'

export const useAppStore = defineStore('app', () => {
  const health = ref<any>(null)
  const loading = ref(false)

  async function checkHealth() {
    try {
      const { data } = await configApi.getHealth()
      health.value = data
    } catch (e) {
      health.value = { status: 'error' }
    }
  }

  return { health, loading, checkHealth }
})
