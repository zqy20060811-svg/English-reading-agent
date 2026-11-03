import { reactive } from 'vue'
import { api, getToken, USER_KEY } from './api/client'
import type { Book } from './types'

// 全局轻量状态：登录用户 / 英语等级 / 书库缓存 / 全局提示
export const store = reactive({
  username: localStorage.getItem(USER_KEY) || '',
  level: null as string | null,
  books: [] as Book[],
  booksLoaded: false,
  toasts: [] as { id: number; text: string; type: string }[],
})

export const LEVEL_NAMES: Record<string, string> = {
  A1: '入门', A2: '基础', B1: '中级', B2: '中高级', C1: '高级',
}
export const DIM_NAMES: Record<string, string> = {
  vocabulary: '词汇', grammar: '语法', reading: '阅读理解',
}

// 按全书词数粗略分档（与书架筛选同源的近似口径）
export function levelOf(wordCount: number): string {
  if (!wordCount) return 'A1'
  if (wordCount < 8000) return 'A1'
  if (wordCount < 20000) return 'A2'
  if (wordCount < 45000) return 'B1'
  if (wordCount < 80000) return 'B2'
  return 'C1'
}

let toastSeq = 0
export function toast(text: string, type: 'error' | 'ok' | 'success' | 'info' = 'error'): void {
  const id = ++toastSeq
  store.toasts.push({ id, text, type })
  setTimeout(() => {
    const i = store.toasts.findIndex(t => t.id === id)
    if (i !== -1) store.toasts.splice(i, 1)
  }, 3000)
}

// 拉取当前用户英语等级（未测试时静默置空）
export async function loadLevel(): Promise<void> {
  if (!getToken()) return
  try {
    store.level = (await api<{ level: string | null }>('/level-test/result')).level
  } catch {
    store.level = null
  }
}

export async function loadBooks(force = false): Promise<Book[]> {
  if (store.booksLoaded && !force) return store.books
  store.books = await api<Book[]>('/books')
  store.booksLoaded = true
  return store.books
}

export function levelText(): string {
  return store.level ? `${store.level} ${LEVEL_NAMES[store.level] || ''}` : '未测试'
}
