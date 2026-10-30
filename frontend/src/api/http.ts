import axios, { type AxiosError, type AxiosRequestConfig } from 'axios'
import router from '../router'
import { TOKEN_KEY } from '../stores/auth'

export interface ApiErrorBody {
  code?: string
  message?: string
  trace_id?: string
  detail?: string
}

export const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
  timeout: 20_000,
  headers: { 'Content-Type': 'application/json' },
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  config.headers['X-Trace-ID'] = crypto.randomUUID()
  return config
})

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiErrorBody>) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem('chargeops_current_user')
      if (router.currentRoute.value.name !== 'login') {
        router.push({ name: 'login', query: { redirect: router.currentRoute.value.fullPath } })
      }
    }
    return Promise.reject(error)
  },
)

export function getApiError(error: unknown) {
  const axiosError = error as AxiosError<ApiErrorBody>
  const data = axiosError.response?.data
  return {
    message: data?.message || data?.detail || axiosError.message || '请求失败，请稍后重试',
    traceId: data?.trace_id || axiosError.response?.headers?.['x-trace-id'] || '',
    status: axiosError.response?.status,
  }
}

export async function request<T>(config: AxiosRequestConfig) {
  const response = await http.request<T>(config)
  return response.data
}

