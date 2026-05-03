import axios, { AxiosError } from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/v1',
  timeout: 30000
})

export class ApiError extends Error {
  status?: number
  code?: string
  details?: unknown

  constructor(message: string, status?: number, code?: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

const extractErrorMessage = (payload: any): string => {
  if (!payload) return '请求失败'
  if (typeof payload === 'string') return payload
  if (payload.message) return payload.message
  if (payload.detail?.message) return payload.detail.message
  if (payload.detail?.error) return payload.detail.error
  if (Array.isArray(payload.detail)) {
    return payload.detail
      .map((item: any) => item.msg || item.message)
      .filter(Boolean)
      .join('; ') || '请求参数无效'
  }
  return payload.error || '请求失败'
}

api.interceptors.response.use(
  response => response,
  (error: AxiosError<any>) => {
    if (error.response) {
      const payload = error.response.data
      return Promise.reject(new ApiError(
        extractErrorMessage(payload),
        error.response.status,
        payload?.code || payload?.detail?.code,
        payload
      ))
    }

    if (error.code === 'ECONNABORTED') {
      return Promise.reject(new ApiError('请求超时，请稍后重试'))
    }

    return Promise.reject(new ApiError(error.message || '网络连接失败'))
  }
)

// 人格 API
export const personaApi = {
  list: () => api.get('/personas'),
  get: (id: string) => api.get(`/personas/${id}`),
  create: (data: any) => api.post('/personas', data),
  update: (id: string, data: any) => api.put(`/personas/${id}`, data),
  delete: (id: string) => api.delete(`/personas/${id}`),
  addVideo: (id: string, data: any) => api.post(`/personas/${id}/videos`, data),
  getTechniques: (id: string) => api.get(`/personas/${id}/techniques`),
  analyzeTechniques: (id: string) => api.post(`/personas/${id}/analyze-techniques`),
  getHookStats: (id: string) => api.get(`/personas/${id}/hook-stats`)
}

// 技法 API
export const techniqueApi = {
  listHooks: (params?: any) => api.get('/hooks', { params }),
  getHook: (id: string) => api.get(`/hooks/${id}`),
  deleteHook: (id: string) => api.delete(`/hooks/${id}`)
}

// 重写 API
export const rewriteApi = {
  batchProcess: (data: any) => api.post('/process/batch', data)
}

// 任务 API
export const taskApi = {
  list: () => api.get('/tasks'),
  getStatus: (id: string) => api.get(`/tasks/${id}/status`),
  getResult: (id: string) => api.get(`/tasks/${id}/result`),
  delete: (id: string) => api.delete(`/tasks/${id}`),
  getVideoTasks: () => api.get('/video-tasks'),
  deleteVideoTask: (id: string) => api.delete(`/video-tasks/${id}`)
}

// ASR API
export const asrApi = {
  fromUrl: (data: any) => api.post('/asr/from-url', data),
  getTaskStatus: (id: string) => api.get(`/asr/tasks/${id}/status`)
}

// 配置 API
export const configApi = {
  getHealth: () => api.get('/health'),
  getBilibili: () => api.get('/config/bilibili'),
  updateBilibili: (data: any) => api.put('/config/bilibili', data)
}

export default api
