// 后端 API 客户端：统一携带 Bearer token，401 时静默刷新令牌并重放请求，失败才回登录页
export const API_BASE: string = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8002'

export const TOKEN_KEY = 'era_access_token'
export const REFRESH_KEY = 'era_refresh_token'
export const USER_KEY = 'era_username'
export const LAST_BOOK_KEY = 'era_last_book'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function logout(): void {
  // 尽力通知后端吊销令牌（失败不阻塞本地登出）
  const token = getToken()
  const refresh = getRefreshToken()
  if (token) {
    fetch(API_BASE + '/auth/logout', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token },
      body: JSON.stringify({ refresh_token: refresh }),
    }).catch(() => {})
  }
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(LAST_BOOK_KEY)
  location.href = '/login'
}

// 静默刷新令牌（绕过 api() 包装，避免递归 401）
async function tryRefresh(): Promise<boolean> {
  const refresh = getRefreshToken()
  if (!refresh) return false
  try {
    const resp = await fetch(API_BASE + '/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    })
    if (!resp.ok) return false
    const data = await resp.json()
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(REFRESH_KEY, data.refresh_token)
    return true
  } catch {
    return false
  }
}

// 并发 401 共享同一次刷新，避免多个请求同时触发 refresh 导致轮换竞争
let refreshingPromise: Promise<boolean> | null = null

interface ApiOptions {
  method?: string
  body?: unknown
  form?: FormData // multipart 上传：设置后忽略 body，由浏览器自动生成 Content-Type 边界
}

// 统一 API 错误：携带 HTTP 状态码与后端错误码，message 为可直接展示的中文文案
export class ApiError extends Error {
  status: number
  code: string

  constructor(message: string, status: number, code = 'unknown') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

// 把后端 detail（字符串 / FastAPI 校验数组 / 对象）归一为可读文案
function normalizeDetail(detail: unknown): string | null {
  if (!detail) return null
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown; field?: unknown } | undefined
    if (first?.msg) return String(first.msg)
  }
  if (typeof detail === 'object' && 'message' in (detail as Record<string, unknown>)) {
    return String((detail as Record<string, unknown>).message)
  }
  return null
}

// 从任意异常中提取可直接展示的文案（视图层统一用它替代 (err as Error).message）
export function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) {
    // 网络层 fetch 失败（后端未启动 / 断网）没有状态码，给友好提示
    return err.message.includes('Failed to fetch') || err.message.includes('NetworkError')
      ? '无法连接服务器，请检查网络后重试'
      : err.message
  }
  return String(err)
}

export async function api<T = any>(path: string, { method = 'GET', body, form }: ApiOptions = {}): Promise<T> {
  const doFetch = (): Promise<Response> =>
    fetch(API_BASE + path, {
      method,
      headers: form
        ? { Authorization: 'Bearer ' + getToken() }
        : { 'Content-Type': 'application/json', Authorization: 'Bearer ' + getToken() },
      body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
    })

  let resp: Response
  try {
    resp = await doFetch()
  } catch (err) {
    throw new ApiError(apiErrorMessage(err), 0, 'network_error')
  }
  if (resp.status === 401) {
    refreshingPromise = refreshingPromise || tryRefresh().finally(() => (refreshingPromise = null))
    const refreshed = await refreshingPromise
    if (!refreshed) {
      logout()
      throw new ApiError('登录已过期', 401, 'unauthorized')
    }
    resp = await doFetch() // 用新令牌重放原请求
  }
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    const d = data as { detail?: unknown; code?: unknown }
    const msg = normalizeDetail(d.detail) || `请求失败（${resp.status}）`
    throw new ApiError(msg, resp.status, typeof d.code === 'string' ? d.code : `http_${resp.status}`)
  }
  return data as T
}
