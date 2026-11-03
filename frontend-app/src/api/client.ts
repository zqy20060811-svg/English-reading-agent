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
}

export async function api<T = any>(path: string, { method = 'GET', body }: ApiOptions = {}): Promise<T> {
  const doFetch = (): Promise<Response> =>
    fetch(API_BASE + path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer ' + getToken(),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })

  let resp = await doFetch()
  if (resp.status === 401) {
    refreshingPromise = refreshingPromise || tryRefresh().finally(() => (refreshingPromise = null))
    const refreshed = await refreshingPromise
    if (!refreshed) {
      logout()
      throw new Error('登录已过期')
    }
    resp = await doFetch() // 用新令牌重放原请求
  }
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    let msg: unknown = (data as { detail?: unknown }).detail || `请求失败（${resp.status}）`
    if (Array.isArray(msg)) msg = (msg[0] as { msg?: unknown }).msg
    throw new Error(String(msg))
  }
  return data as T
}
