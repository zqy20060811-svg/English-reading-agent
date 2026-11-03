// 与后端 schemas 对齐的前端类型定义（按需补充）

// BookCover 组件所需的最小书籍字段
export interface CoverBook {
  title: string
  author: string
  cover_url: string | null
}

export interface Book {
  id: number
  gutenberg_id: number
  title: string
  author: string
  year: number
  genre: string
  synopsis: string
  cover_url: string | null
  language: string
  word_count: number
}

export interface ChapterMeta {
  chapter_index: number
  title: string
}

export interface Chapter extends ChapterMeta {
  book_id?: number
  content: string
}

export interface ReadingProgress {
  book_id: number
  chapter_index: number
  char_offset: number
  page_index: number
  percent: number
  updated_at: string
}

// localStorage 记录的最近阅读位置
export interface LastBook {
  book_id: number
  chapter_index: number
  percent: number
}

// /books/{id}/hot 返回的互动状态
export interface BookInteraction {
  liked: boolean
  favorited: boolean
  like_count: number
  favorite_count: number
}

// 点词查义结果
export interface WordLookup {
  word: string
  phonetic: string
  senses: string[]
  example_en: string
  example_cn: string
  cached: boolean
}

// 生词条目
export interface VocabItem {
  id: number
  book_id: number
  book_title: string
  word: string
  context_sentence: string | null
  chapter_index: number
  created_at: string
}

// 书签条目
export interface BookmarkItem {
  id: number
  book_id: number
  book_title: string
  chapter_index: number
  page_index: number
  excerpt: string
  created_at: string
}

// /me/history 返回的阅读历史条目
export interface HistoryItem {
  book_id: number
  title: string
  author: string
  cover_url: string | null
  chapter_index: number
  percent: number
  updated_at: string
}

// AI 问答历史条目
export interface QAItem {
  role: 'me' | 'ai' | 'err'
  text: string
  scope?: string
}

// 点词查义浮层状态
export interface LookupPop {
  word: string
  sentence: string
  x: number
  y: number
  loading: boolean
  data: WordLookup | null
  error: string
  saved: boolean
}

// 划句翻译浮层定位
export interface SelBubble {
  x: number
  y: number
  text: string
}

// /me 返回的当前用户信息
export interface UserInfo {
  id: number
  username: string
  email: string
  email_verified: boolean
  is_admin: boolean
  created_at: string
}

// ============ 管理后台 ============

export interface AdminBook {
  id: number
  gutenberg_id: number
  title: string
  author: string
  year: number
  genre: string
  word_count: number
  is_active: boolean
}

export interface AdminUser {
  id: number
  username: string
  email: string
  email_verified: boolean
  is_admin: boolean
  is_disabled: boolean
  created_at: string
}

export interface IngestTask {
  id: number
  gutenberg_id: number
  embed: boolean
  status: 'pending' | 'running' | 'success' | 'failed'
  attempts: number
  error: string | null
  created_by: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface SceneUsage {
  scene: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
}

export interface DailyUsage {
  day: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
}

export interface AIStats {
  days: number
  total_calls: number
  total_prompt_tokens: number
  total_completion_tokens: number
  total_cost_usd: number
  by_scene: SceneUsage[]
  by_day: DailyUsage[]
}

export interface AdminOverview {
  total_users: number
  total_books: number
  active_books: number
  running_or_pending_tasks: number
  ai_calls_today: number
}
