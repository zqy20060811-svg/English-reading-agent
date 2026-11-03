// api 客户端错误处理单元测试：detail 归一化 / ApiError 状态码与错误码 / 网络错误文案
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, apiErrorMessage } from '../src/api/client'

function mockFetchOnce(status: number, body: unknown): void {
  vi.stubGlobal('fetch', vi.fn(async () =>
    new Response(JSON.stringify(body), { status })))
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('api 错误归一化', () => {
  it('字符串 detail 原样透出，携带状态码与后端错误码', async () => {
    mockFetchOnce(429, { detail: '今日翻译额度已用完', code: 'quota_exceeded' })
    const err = await api('/translate', { method: 'POST', body: {} }).catch(e => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toBe('今日翻译额度已用完')
    expect(err.status).toBe(429)
    expect(err.code).toBe('quota_exceeded')
  })

  it('FastAPI 校验数组 detail 取第一条 msg', async () => {
    mockFetchOnce(422, { detail: [{ msg: 'field required', loc: [] }] })
    const err = await api('/x').catch(e => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toBe('field required')
    expect(err.code).toBe('http_422')
  })

  it('无 detail 时使用通用文案', async () => {
    mockFetchOnce(500, {})
    const err = await api('/x').catch(e => e)
    expect(err.message).toBe('请求失败（500）')
    expect(err.code).toBe('http_500')
  })

  it('网络层失败映射为友好文案 + network_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const err = await api('/x').catch(e => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toBe('无法连接服务器，请检查网络后重试')
    expect(err.code).toBe('network_error')
    expect(err.status).toBe(0)
  })

  it('成功请求返回解析后的 JSON', async () => {
    mockFetchOnce(200, { ok: 1 })
    expect(await api<{ ok: number }>('/x')).toEqual({ ok: 1 })
  })
})

describe('apiErrorMessage', () => {
  it('ApiError 直接取 message', () => {
    expect(apiErrorMessage(new ApiError('配额不足', 429))).toBe('配额不足')
  })

  it('普通 Error 原样取 message', () => {
    expect(apiErrorMessage(new Error('boom'))).toBe('boom')
  })

  it('非 Error 值转字符串', () => {
    expect(apiErrorMessage('直接字符串')).toBe('直接字符串')
  })
})
