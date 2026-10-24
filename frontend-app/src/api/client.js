// 后端 API 客户端：统一携带 Bearer token，401 自动清登录态回登录页
export const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8002'

export const TOKEN_KEY = 'era_access_token'
export const USER_KEY = 'era_username'
export const LAST_BOOK_KEY = 'era_last_book'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(LAST_BOOK_KEY)
  location.href = '/login'
}

export async function api(path, { method = 'GET', body } = {}) {
  const resp = await fetch(API_BASE + path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      Authorization: 'Bearer ' + getToken(),
    },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (resp.status === 401) {
    logout()
    throw new Error('登录已过期')
  }
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    let msg = data.detail || `请求失败（${resp.status}）`
    if (Array.isArray(msg)) msg = msg[0].msg
    throw new Error(msg)
  }
  return data
}
