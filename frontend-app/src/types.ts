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

// ============ 个人上传书籍（/personal/books） ============

export interface PersonalBook {
  id: number
  title: string
  author: string
  language: string
  source_type: string // 'epub' | 'txt'
  original_filename: string
  file_size: number
  word_count: number
  chapter_count: number
  created_at: string
}

export interface PersonalBookUploadOut extends PersonalBook {
  duplicated: boolean // true = 命中同人同文件，复用已有记录
}

// ============ 个人书籍 AI 全书分析（/personal/books/{id}/analysis） ============

export type AnalysisStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface PersonalAnalysisTask {
  id: number
  personal_book_id: number
  status: AnalysisStatus
  total_chapters: number
  completed_chapters: number
  failed_chapters: number
  current_chapter_index: number | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface PersonalChapterAnalysis {
  chapter_index: number
  word_count: number
  unique_word_count: number
  average_sentence_length: number
  long_sentence_ratio: number
  vocabulary_level_distribution: Record<string, number>
  vocabulary_statistics: {
    unique_word_count: number
    top_freq_words: { word: string; count: number }[]
    unknown_words: { word: string; count: number }[]
  }
  grammar_features: {
    local_rules?: Record<string, { count: number; examples?: string[] }>
    llm_focus?: { pattern: string; example: string; explanation: string }[]
  }
  difficulty_level: string
  difficulty_score: number
  chapter_summary: string
  reading_suggestion: string
  analysis_version: number
  updated_at: string
}

export interface PersonalBookReport {
  overall_level: string
  difficulty_score: number
  total_word_count: number
  chapter_difficulty_distribution: Record<string, number>
  vocabulary_level_distribution: Record<string, number>
  main_grammar_features: Record<string, { count: number }>
  reading_recommendations: string[]
  analysis_version: number
  completed_at: string
}

// ============ 个人书籍个性化预测（/personal/books/{id}/chapters/{n}/prediction） ============

// 预测生词候选
export interface PredictedWord {
  word: string          // 归一化小写
  level: string         // CEFR 等级（A1~C2），词典未收录为 unknown
  count: number         // 在本章出现次数
  in_vocabulary: boolean // 是否已在用户生词本中
}

// 预测长难句候选
export interface PredictedSentence {
  sentence_index: number  // 句子在章节中的序号（1 开始）
  char_start: number | null // 章节正文中的字符偏移（定位失败为 null）
  word_count: number
  clause_markers: number
  text: string
}

// 单章预测结果
export interface ChapterPrediction {
  chapter_index: number
  title: string
  words: PredictedWord[]
  sentences: PredictedSentence[]
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
