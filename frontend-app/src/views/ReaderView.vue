<script setup lang="ts">
// 阅读器：固定高度分页（CSS 多列平移）+ 章节目录 + AI 抽屉（问答 / 翻译本页）+ 可拖动悬浮按钮
// 拆分后的子组件：AiDrawer / AiFab / BookmarkPanel / WordLookupPopup / SelectionTranslatePopup
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, LAST_BOOK_KEY, apiErrorMessage } from '../api/client'
import { loadBooks, store, toast } from '../store'
import type { Book, BookmarkItem, BookInteraction, Chapter, ChapterMeta, ChapterPrediction, LookupPop, PersonalAnalysisTask, PersonalBook, PersonalBookReport, PredictedWord, QAItem, ReadingProgress, SelBubble, VocabItem, WordLookup } from '../types'
import { buildSegments, locateSentence, mapParagraphs, wordMapOf, type ParaSegment } from '../utils/personalPrediction'
import { extractWordAt } from '../utils/wordExtract'
import AiDrawer from '../components/reader/AiDrawer.vue'
import AiFab from '../components/reader/AiFab.vue'
import BookmarkPanel from '../components/reader/BookmarkPanel.vue'
import WordLookupPopup from '../components/reader/WordLookupPopup.vue'
import SelectionTranslatePopup from '../components/reader/SelectionTranslatePopup.vue'

const route = useRoute()
const router = useRouter()

const bookId = ref<number | null>(null)
// 个人书籍来源（/read/personal/:bookId）：API 走 /personal/books，隐藏公共书专属功能
const isPersonal = computed(() => route.name === 'reader-personal')
const base = computed(() => (isPersonal.value ? '/personal/books' : '/books'))
const personalBooks = ref<PersonalBook[]>([])
const chapters = ref<ChapterMeta[]>([])
const chapter = ref<(Chapter & { word_count: number }) | null>(null)
const loadingChapter = ref(false)
const chapterError = ref('') // 章节加载失败信息（非空时展示重试按钮）

// ================= 个人书籍 AI 辅助（阶段D：章节预测 + 分析状态） =================
const prediction = ref<ChapterPrediction | null>(null)
const predictionLoading = ref(false)
const predictionError = ref('')
let predictionReqId = 0 // 竞态防护：章节切换后旧响应按序号丢弃

// 分析状态条数据（全部静默失败，不阻断阅读）
const analysisStatus = ref<PersonalAnalysisTask | null>(null)
const analysisReport = ref<PersonalBookReport | null>(null)
const myLevel = ref<string | null>(null) // 最新等级测试结果；null = 未测试（后端默认按 B1 估算）
let analysisTimer: number | undefined

// 分页状态
const PAGE_GAP = 64
const page = ref(0)
const pages = ref(1)
const pagesShell = ref<HTMLElement | null>(null)
const pagesInner = ref<HTMLElement | null>(null)

// AI 抽屉
const drawerOpen = ref(false)
const aiTab = ref<'qa' | 'tr'>('qa')
const qaHistory = ref<QAItem[]>([]) // [{ role: 'me'|'ai'|'err', text, scope }]
const qaSending = ref(false)
const translating = ref(false)
const pageTranslation = ref('')

const shellHeight = 'max(480px, calc(100vh - 200px))' // 矮视口下保底高度，避免每列字数过少

const book = computed<Book | PersonalBook | null>(() =>
  isPersonal.value
    ? personalBooks.value.find(b => b.id === bookId.value) || null
    : store.books.find(b => b.id === bookId.value) || null)

// 顶部书籍信息行：公共书显示 作者/年份/词数，个人书显示 作者/语言/词数
const bookMetaLine = computed(() => {
  const b = book.value
  if (!b) return ''
  if (isPersonal.value) {
    return `${b.author ? b.author + ' · ' : ''}${b.language.toUpperCase()} · ${(b.word_count / 10000).toFixed(1)} 万词`
  }
  const pub = b as Book
  return `${pub.author} · ${pub.year}${pub.word_count ? ` · ${(pub.word_count / 10000).toFixed(1)} 万词` : ''}`
})
const percent = computed(() =>
  chapter.value && chapters.value.length ? (chapter.value.chapter_index / chapters.value.length) * 100 : 0)

// 下一章标题（章末过渡页用；最后一章为 null）
const nextChapterTitle = computed<string | null>(() => {
  if (!chapter.value || chapter.value.chapter_index >= chapters.value.length) return null
  const next = chapters.value.find(c => c.chapter_index === chapter.value!.chapter_index + 1)
  return next ? `第 ${next.chapter_index} 章 · ${next.title}` : null
})

// ================= 初始化与书目切换 =================

// 我的书单：读过/点赞/收藏过的书（下拉不再展示全库）
const myBooks = ref<Book[]>([])

async function loadMyBooks(): Promise<void> {
  try {
    myBooks.value = await api<Book[]>('/books/mine')
  } catch { /* 拉取失败时下拉留空，提示去书库选书 */ }
}

// 个人书籍下拉数据源
async function loadPersonalBooks(): Promise<void> {
  try {
    personalBooks.value = await api<PersonalBook[]>('/personal/books')
  } catch (err) {
    toast('个人书籍加载失败：' + apiErrorMessage(err))
  }
}

// 顶部选书下拉的数据源：个人模式用上传列表，公共模式用我的书单
const selectList = computed<{ id: number; title: string }[]>(() =>
  isPersonal.value ? personalBooks.value : myBooks.value)

onMounted(async () => {
  if (isPersonal.value) {
    await loadPersonalBooks()
  } else {
    try {
      await loadBooks()
    } catch (err) {
      toast('书库加载失败：' + apiErrorMessage(err))
    }
    await loadMyBooks()
  }
  const param = parseInt(route.params.bookId as string)
  if (param) {
    await onBookChange(param, 0) // 0 = 读服务端进度
  }
})

async function onBookChange(id: number, chapterIndex = 1): Promise<void> {
  bookId.value = id || null
  chapter.value = null
  chapters.value = []
  qaHistory.value = []
  pageTranslation.value = ''
  bookmarks.value = []
  chapterError.value = ''
  // 个人书 AI 辅助状态重置（换书/换来源时旧书数据不可残留）
  prediction.value = null
  predictionError.value = ''
  analysisStatus.value = null
  analysisReport.value = null
  stopAnalysisPoll()
  if (!id) return
  // 当前书保证出现在下拉里（首次从书库进入时可能还没有互动记录）
  if (!isPersonal.value && !myBooks.value.some(b => b.id === id)) {
    const b = store.books.find(x => x.id === id)
    if (b) myBooks.value = [...myBooks.value, b]
  }
  try {
    chapters.value = await api<ChapterMeta[]>(`${base.value}/${id}/chapters`)
    // 未指定章节：优先服务端进度（章节 + 页内断点），兜底第 1 章
    let resumePage = 0
    if (!chapterIndex || chapterIndex < 1) {
      try {
        const p = await api<ReadingProgress>(`${base.value}/${id}/progress`)
        chapterIndex = Math.min(p.chapter_index, chapters.value.length) || 1
        resumePage = p.page_index || 0
      } catch {
        chapterIndex = 1
      }
    }
    await loadChapter(chapterIndex, resumePage)
    if (!isPersonal.value) {
      loadInteraction() // 点赞/收藏状态与计数（失败静默）
      loadBookmarks() // 书签列表（失败静默）
    } else {
      loadAnalysisInfo() // 分析状态条：水平 / 任务进度 / 全书难度（失败静默）
    }
  } catch (err) {
    toast('章节目录加载失败：' + apiErrorMessage(err))
  }
}

function onSelectChange(e: Event): void {
  const id = parseInt((e.target as HTMLSelectElement).value)
  if (id) router.replace({ name: isPersonal.value ? 'reader-personal' : 'reader', params: { bookId: String(id) } })
  onBookChange(id)
}

// ================= 章节加载 =================
async function loadChapter(index: number, startPage = 0): Promise<void> {
  if (!chapters.value.length || !bookId.value) return
  index = Math.max(1, Math.min(index, chapters.value.length))
  loadingChapter.value = true
  chapterError.value = ''
  try {
    const data = await api<Chapter & { word_count: number }>(`${base.value}/${bookId.value}/chapters/${index}`)
    chapter.value = data
    pageTranslation.value = ''
    loadingChapter.value = false // 先退出加载态，正文 DOM 挂载后才能测量分页
    await nextTick()
    await new Promise(r => requestAnimationFrame(r)) // 再等一帧，确保布局完成
    paginate()
    // 断点续读：恢复服务端保存的页内位置
    if (startPage > 0 && startPage < pages.value) {
      page.value = startPage
      updatePageUI()
    }
    saveProgress()
    // 个人书：并行加载本章预测（不阻塞正文，竞态由请求序号防护）
    if (isPersonal.value) loadPrediction(data.chapter_index)
    // 最近阅读位置仅记录公共书：书架「继续阅读」按公共书路由恢复，避免个人书 id 撞公共书
    if (!isPersonal.value) {
      localStorage.setItem(LAST_BOOK_KEY, JSON.stringify({
        book_id: bookId.value, chapter_index: data.chapter_index, percent: percent.value,
      }))
    }
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (err) {
    chapterError.value = apiErrorMessage(err) // 阅读框内展示失败态，支持重试
  } finally {
    loadingChapter.value = false
  }
}

function retryChapter(): void {
  if (chapter.value) loadChapter(chapter.value.chapter_index)
  else if (chapters.value.length) loadChapter(1)
}

async function saveProgress(): Promise<void> {
  if (!chapter.value || !bookId.value) return
  try {
    await api(`${base.value}/${bookId.value}/progress`, {
      method: 'PUT',
      body: {
        chapter_index: chapter.value.chapter_index,
        char_offset: 0,
        page_index: page.value,
        percent: Math.min(percent.value, 100),
      },
    })
  } catch { /* 进度保存失败不阻塞阅读 */ }
}

// 翻页时的防抖进度保存，避免频繁请求
let saveTimer: ReturnType<typeof setTimeout> | undefined
function saveProgressDebounced(): void {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(saveProgress, 1500)
}

const prevChapter = () => chapter.value && loadChapter(chapter.value.chapter_index - 1)

function reportFinish(): void {
  // 进入下一章视为读完当前章：上报热度事件（同人同书每日限计 1 次，失败静默）
  // 热度是公共书库概念，个人书籍不上报
  if (!bookId.value || !chapter.value || isPersonal.value) return
  api(`/books/${bookId.value}/events`, {
    method: 'POST',
    body: { event_type: 'finish_chapter' },
  }).catch(() => {})
}

function nextChapter(): void {
  if (!chapter.value) return
  reportFinish()
  loadChapter(chapter.value.chapter_index + 1)
}

// ================= 点赞 / 收藏（热度行为） =================
const liked = ref(false)
const favorited = ref(false)
const likeCount = ref(0)
const favCount = ref(0)

async function loadInteraction(): Promise<void> {
  if (!bookId.value) return
  try {
    const d = await api<BookInteraction>(`/books/${bookId.value}/hot`)
    liked.value = d.liked
    favorited.value = d.favorited
    likeCount.value = d.like_count
    favCount.value = d.favorite_count
  } catch { /* 热度信息加载失败不阻塞阅读 */ }
}

async function toggleLike(): Promise<void> {
  if (!bookId.value) return
  try {
    const d = await api<BookInteraction>(`/books/${bookId.value}/like`, { method: 'POST' })
    liked.value = d.liked
    likeCount.value = d.like_count
    toast(d.liked ? '已点赞' : '已取消点赞', 'ok')
  } catch (err) {
    toast('操作失败：' + apiErrorMessage(err))
  }
}

async function toggleFavorite(): Promise<void> {
  if (!bookId.value) return
  try {
    const d = await api<BookInteraction>(`/books/${bookId.value}/favorite`, { method: 'POST' })
    favorited.value = d.favorited
    favCount.value = d.favorite_count
    toast(d.favorited ? '已加入收藏' : '已取消收藏', 'ok')
  } catch (err) {
    toast('操作失败：' + apiErrorMessage(err))
  }
}

// ================= 分页（CSS 多列横向平移） =================
function pageMetrics(): { w: number; padL: number; padR: number } {
  const shell = pagesShell.value!
  const cs = getComputedStyle(shell)
  const w = shell.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
  return { w, padL: parseFloat(cs.paddingLeft), padR: parseFloat(cs.paddingRight) }
}

function paginate(): void {
  if (!chapter.value || !pagesShell.value || !pagesInner.value) return
  const { w, padL, padR } = pageMetrics()
  const inner = pagesInner.value
  inner.style.columnWidth = w + 'px'
  inner.style.columnGap = PAGE_GAP + 'px'
  inner.style.columnFill = 'auto'
  page.value = 0
  pages.value = Math.max(1, Math.ceil((pagesShell.value.scrollWidth - padL - padR + PAGE_GAP) / (w + PAGE_GAP)) || 1)
  updatePageUI()
}

function updatePageUI(): void {
  const { w } = pageMetrics()
  if (pagesInner.value) pagesInner.value.style.transform = `translateX(-${page.value * (w + PAGE_GAP)}px)`
  // 翻页后旧页译文失效
  pageTranslation.value = ''
}

function prevPage(): void {
  if (page.value > 0) { page.value--; updatePageUI(); saveProgressDebounced() }
}

function nextPage(): void {
  if (page.value < pages.value - 1) { page.value++; updatePageUI(); saveProgressDebounced() }
  else if (chapter.value && chapter.value.chapter_index < chapters.value.length) nextChapter()
}

// 移动端左右滑动翻页：水平位移超过阈值即翻页，选中文字时不触发
const SWIPE_MIN = 60
let touchStart: { x: number; y: number } | null = null

function onTouchStart(e: TouchEvent): void {
  if (e.touches.length !== 1) { touchStart = null; return }
  touchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY }
}

function onTouchEnd(e: TouchEvent): void {
  if (!touchStart) return
  const t = e.changedTouches[0]
  const dx = t.clientX - touchStart.x
  const dy = t.clientY - touchStart.y
  touchStart = null
  if (Math.abs(dx) < SWIPE_MIN || Math.abs(dx) < Math.abs(dy) * 2) return // 垂直滚动不误触
  if (window.getSelection()?.toString()) return // 划词选中文本时不翻页
  if (dx < 0) nextPage()
  else prevPage()
}

let resizeTimer: ReturnType<typeof setTimeout> | undefined
function onResize(): void {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(paginate, 200)
}

function onKeydown(e: KeyboardEvent): void {
  if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return
  if (e.key === 'ArrowLeft') prevPage()
  if (e.key === 'ArrowRight') nextPage()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  document.addEventListener('keydown', onKeydown)
  document.addEventListener('selectionchange', onSelectionChange)
  loadMyVocabulary() // 生词本已收藏索引（公共书/个人书都用，失败静默）
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('selectionchange', onSelectionChange)
  stopAnalysisPoll()
})

// ================= 翻译本页（仅当前可见页） =================
function currentPageText(): string {
  if (!pagesInner.value || !pagesShell.value) return ''
  const paras = Array.from(pagesInner.value.querySelectorAll('p'))
  if (!paras.length) return ''
  const { w } = pageMetrics()
  const shellLeft = pagesShell.value.getBoundingClientRect().left
  const visible = paras.filter(p => {
    const left = p.getBoundingClientRect().left - shellLeft
    return left >= -4 && left < w - 4
  })
  return (visible.length ? visible : paras).map(p => p.textContent).join('\n\n')
}

async function translatePage(): Promise<void> {
  if (!chapter.value) { toast('请先选择一本书'); return }
  const text = currentPageText().slice(0, 4500)
  if (!text.trim()) { toast('当前页没有可翻译的内容'); return }
  translating.value = true
  try {
    const result = await api<{ translation: string }>('/translate', { method: 'POST', body: { text, target_lang: '中文' } })
    pageTranslation.value = result.translation
  } catch (err) {
    toast('翻译失败：' + apiErrorMessage(err))
  } finally {
    translating.value = false
  }
}

// ================= AI 问答（RAG，限定当前章节） =================
async function askQuestion(question: string): Promise<void> {
  if (!chapter.value || !bookId.value) { toast('请先选择一本书和章节'); return }
  if (isPersonal.value) {
    qaHistory.value.push({ role: 'err', text: '个人书籍的 AI 问答还在路上，敬请期待（当前可使用划句翻译与点词查义）' })
    return
  }
  if (!question || qaSending.value) return
  qaSending.value = true
  qaHistory.value.push({ role: 'me', text: question })
  try {
    const result = await api<{ answer: string; scope: string }>('/ask/reading', {
      method: 'POST',
      body: { book_id: bookId.value, chapter_index: chapter.value.chapter_index, question },
    })
    qaHistory.value.push({ role: 'ai', text: result.answer, scope: result.scope })
  } catch (err) {
    qaHistory.value.push({ role: 'err', text: '回答失败：' + apiErrorMessage(err) })
  } finally {
    qaSending.value = false
  }
}

// ================= 个人书预测与分析状态（阶段D） =================

/** 当前章节预测数据：只请求单章，切章重载，竞态用请求序号防护 */
async function loadPrediction(index: number): Promise<void> {
  if (!isPersonal.value || !bookId.value) return
  const reqId = ++predictionReqId
  predictionLoading.value = true
  predictionError.value = ''
  try {
    const data = await api<ChapterPrediction>(`${base.value}/${bookId.value}/chapters/${index}/prediction`)
    if (reqId !== predictionReqId) return // 章节已切换，丢弃旧响应
    prediction.value = data
  } catch (err) {
    if (reqId !== predictionReqId) return
    prediction.value = null
    predictionError.value = apiErrorMessage(err) // 预测失败只提示重试，不影响正文
  } finally {
    if (reqId === predictionReqId) predictionLoading.value = false
  }
}

function retryPrediction(): void {
  if (chapter.value) loadPrediction(chapter.value.chapter_index)
}

/** 分析状态条：用户水平 + 任务进度 + 全书难度（全部静默失败，不阻断阅读） */
async function loadAnalysisInfo(): Promise<void> {
  if (!isPersonal.value || !bookId.value) return
  stopAnalysisPoll()
  const id = bookId.value
  api<{ level: string | null }>('/me/stats')
    .then(s => { if (bookId.value === id) myLevel.value = s.level })
    .catch(() => { /* 水平展示为未知 */ })
  api<PersonalAnalysisTask>(`${base.value}/${id}/analysis/status`)
    .then(t => {
      if (bookId.value !== id) return
      analysisStatus.value = t
      if (['pending', 'running'].includes(t.status)) {
        analysisTimer = analysisTimer ?? window.setInterval(refreshAnalysisStatus, 5000)
      }
    })
    .catch(() => { /* 无分析任务属正常状态 */ })
  api<PersonalBookReport>(`${base.value}/${id}/analysis/report`)
    .then(r => { if (bookId.value === id) analysisReport.value = r })
    .catch(() => { /* 报告未生成属正常状态 */ })
}

/** 进行中任务轮询：完成后拉一次报告并停止 */
async function refreshAnalysisStatus(): Promise<void> {
  if (!isPersonal.value || !bookId.value) { stopAnalysisPoll(); return }
  try {
    const t = await api<PersonalAnalysisTask>(`${base.value}/${bookId.value}/analysis/status`)
    analysisStatus.value = t
    if (!['pending', 'running'].includes(t.status)) {
      stopAnalysisPoll()
      if (t.status === 'completed') {
        api<PersonalBookReport>(`${base.value}/${bookId.value}/analysis/report`)
          .then(r => { analysisReport.value = r }).catch(() => {})
      }
    }
  } catch { /* 状态刷新失败保持旧值 */ }
}

function stopAnalysisPoll(): void {
  if (analysisTimer) { window.clearInterval(analysisTimer); analysisTimer = undefined }
}

/** 生词本已收藏索引：word → 生词条目 id（高亮样式与取消收录都要用） */
async function loadMyVocabulary(): Promise<void> {
  try {
    const rows = await api<VocabItem[]>('/vocabulary')
    const map = new Map<string, number>()
    rows.forEach(r => map.set(r.word, r.id))
    savedWordIds.value = map
  } catch { /* 收录状态加载失败只影响样式与按钮 */ }
}

function isWordSaved(word: string): boolean {
  return savedWordIds.value.has(word)
}

// ================= 正文渲染片段（高亮在数据层切片，Vue 渲染，不碰 DOM） =================
const displayParas = computed<{ text: string; segs: ParaSegment[] }[]>(() => {
  if (!chapter.value) return []
  const paras = mapParagraphs(chapter.value.content)
  if (!isPersonal.value || !prediction.value) {
    return paras.map(p => ({ text: p.text, segs: [{ text: p.text }] }))
  }
  const words = wordMapOf(prediction.value.words)
  const located = prediction.value.sentences
    .map(s => locateSentence(paras, s))
    .filter((r): r is NonNullable<typeof r> => r !== null)
  return paras.map((p, i) => ({
    text: p.text,
    segs: buildSegments(p.text, words, located.filter(r => r.paraIndex === i).map(r => r.range)),
  }))
})

// ================= 点词查义（点击正文单词弹出释义卡片） =================
const lookup = ref<LookupPop | null>(null)
const lookupPrediction = ref<PredictedWord | null>(null) // 弹层关联的预测信息（个人书）
const savedWordIds = ref(new Map<string, number>()) // 生词本已收藏：归一化 word → 条目 id

const POP_W = 288
function popupPos(e: MouseEvent): { x: number; y: number } {
  return {
    x: Math.min(Math.max(8, e.clientX - POP_W / 2), window.innerWidth - POP_W - 12),
    y: Math.min(e.clientY + 16, window.innerHeight - 300),
  }
}

async function onContentClick(e: MouseEvent): Promise<void> {
  selResult.value = null
  if (window.getSelection()?.toString()) return // 划词中不触发点词
  const target = e.target as HTMLElement
  if (!target.closest('p')) return // 只对正文段落生效（章末按钮等不受影响）
  // 个人书：预测生词 / 长难句的高亮交互优先
  if (isPersonal.value) {
    const wordEl = target.closest('span[data-era-word]') as HTMLElement | null
    if (wordEl) { openPredictionWordPopup(wordEl, e); return }
    const sentEl = target.closest('span[data-era-sentence]') as HTMLElement | null
    if (sentEl) { openSentenceTranslate(sentEl, e); return }
  }
  const hit = extractWordAt(document, e.clientX, e.clientY)
  if (!hit || !bookId.value || !chapter.value) return
  openLookupPopup(hit.word.toLowerCase(), hit.sentence, popupPos(e), null)
}

/** 打开查词弹层：公共书任意词 / 个人书预测生词共用 */
async function openLookupPopup(word: string, sentence: string, pos: { x: number; y: number }, pw: PredictedWord | null): Promise<void> {
  lookupPrediction.value = pw
  lookup.value = {
    word, sentence: sentence, x: pos.x, y: pos.y,
    loading: true, data: null, error: '', saved: savedWordIds.value.has(word),
  }
  try {
    const data = await api<WordLookup>(`/lookup/word/${encodeURIComponent(word)}`)
    if (lookup.value && lookup.value.word === word) lookup.value.data = data
  } catch (err) {
    if (lookup.value && lookup.value.word === word) lookup.value.error = apiErrorMessage(err)
  } finally {
    if (lookup.value && lookup.value.word === word) lookup.value.loading = false
  }
}

function openPredictionWordPopup(el: HTMLElement, e: MouseEvent): void {
  const word = el.dataset.eraWord || ''
  if (!word || !chapter.value) return
  const pw = prediction.value?.words.find(w => w.word === word) ?? null
  // 上下文例句：优先所在长难句，否则所在段落
  const sentEl = el.closest('span[data-era-sentence]') as HTMLElement | null
  const sentence = (sentEl?.textContent || el.closest('p')?.textContent || '').trim().slice(0, 400)
  openLookupPopup(word, sentence, popupPos(e), pw)
}

async function saveToVocabulary(): Promise<void> {
  const l = lookup.value
  if (!l || !bookId.value || !chapter.value || l.saved) return
  try {
    const body: Record<string, unknown> = {
      word: l.word,
      chapter_index: chapter.value.chapter_index,
      context_sentence: l.sentence || null,
    }
    if (!isPersonal.value) body.book_id = bookId.value // 公共书必传；个人书不传（后端 book_id 可空）
    const out = await api<{ id: number }>('/vocabulary', { method: 'POST', body })
    savedWordIds.value.set(l.word, out.id)
    l.saved = true
    toast('已收录到生词本', 'success')
  } catch (err) {
    toast('收录失败：' + apiErrorMessage(err))
  }
}

async function removeFromVocabulary(): Promise<void> {
  const l = lookup.value
  if (!l) return
  const id = savedWordIds.value.get(l.word)
  if (!id) return
  try {
    await api(`/vocabulary/${id}`, { method: 'DELETE' })
    savedWordIds.value.delete(l.word)
    l.saved = false
    toast('已从生词本移除', 'ok')
  } catch (err) {
    toast('移除失败：' + apiErrorMessage(err))
  }
}

// ================= 长难句点击（复用现有翻译能力，直接出译文卡片） =================
async function openSentenceTranslate(el: HTMLElement, e: MouseEvent): Promise<void> {
  const text = (el.textContent || '').trim()
  if (!text || selTranslating.value) return
  const x = Math.min(Math.max(60, e.clientX), window.innerWidth - 80)
  const y = Math.min(e.clientY + 24, window.innerHeight - 160)
  selResult.value = { x, y, text: '' }
  selTranslating.value = true
  try {
    const r = await api<{ translation: string }>('/translate', {
      method: 'POST', body: { text, target_lang: '中文' },
    })
    selResult.value = { x, y, text: r.translation }
  } catch (err) {
    selResult.value = { x, y, text: '翻译失败：' + apiErrorMessage(err) }
  } finally {
    selTranslating.value = false
  }
}

// ================= 划句翻译（选中正文句子浮现翻译按钮） =================
const selBar = ref<SelBubble | null>(null)
const selResult = ref<SelBubble | null>(null)
const selTranslating = ref(false)

let selTimer: ReturnType<typeof setTimeout> | undefined
function onSelectionChange(): void {
  clearTimeout(selTimer)
  selTimer = setTimeout(() => {
    const sel = window.getSelection()
    const text = sel?.toString().trim() || ''
    if (!text || text.length < 2 || text.length > 600 || !sel || sel.isCollapsed) {
      selBar.value = null
      return
    }
    const shell = pagesShell.value
    const range = sel.getRangeAt(0)
    if (!shell || !shell.contains(range.commonAncestorContainer)) { selBar.value = null; return }
    const rect = range.getBoundingClientRect()
    if (!rect.width && !rect.height) { selBar.value = null; return }
    selBar.value = {
      x: Math.min(Math.max(60, rect.left + rect.width / 2), window.innerWidth - 80),
      y: Math.max(8, rect.top - 46),
      text,
    }
  }, 300)
}

async function translateSelection(): Promise<void> {
  const sb = selBar.value
  if (!sb || selTranslating.value) return
  selTranslating.value = true
  const x = sb.x
  const y = sb.y
  selResult.value = { x, y, text: '' }
  selBar.value = null
  try {
    const r = await api<{ translation: string }>('/translate', {
      method: 'POST',
      body: { text: sb.text, target_lang: '中文' },
    })
    selResult.value = { x, y, text: r.translation }
  } catch (err) {
    selResult.value = { x, y, text: '翻译失败：' + apiErrorMessage(err) }
  } finally {
    selTranslating.value = false
  }
}

// ================= 书签（添加 / 列表 / 跳转 / 删除） =================
const bookmarks = ref<BookmarkItem[]>([])
const showBookmarks = ref(false)

// 当前页是否已有书签（控制按钮高亮与移除）
const pageBookmarked = computed(() =>
  bookmarks.value.some(b =>
    b.book_id === bookId.value &&
    b.chapter_index === chapter.value?.chapter_index &&
    b.page_index === page.value))

async function loadBookmarks(): Promise<void> {
  if (!bookId.value) return
  try {
    bookmarks.value = await api<BookmarkItem[]>(`/bookmarks?book_id=${bookId.value}`)
  } catch { /* 书签加载失败不阻塞阅读 */ }
}

async function toggleBookmark(): Promise<void> {
  if (!bookId.value || !chapter.value) { toast('请先选择一本书'); return }
  const existing = bookmarks.value.find(b =>
    b.book_id === bookId.value &&
    b.chapter_index === chapter.value!.chapter_index &&
    b.page_index === page.value)
  try {
    if (existing) {
      await api(`/bookmarks/${existing.id}`, { method: 'DELETE' })
      bookmarks.value = bookmarks.value.filter(b => b.id !== existing.id)
      toast('已移除书签', 'ok')
    } else {
      const excerpt = currentPageText().replace(/\s+/g, ' ').trim().slice(0, 80)
      await api('/bookmarks', {
        method: 'POST',
        body: {
          book_id: bookId.value,
          chapter_index: chapter.value.chapter_index,
          page_index: page.value,
          excerpt,
        },
      })
      await loadBookmarks()
      toast('已添加书签', 'success')
    }
  } catch (err) {
    toast('书签操作失败：' + apiErrorMessage(err))
  }
}

function jumpToBookmark(b: BookmarkItem): void {
  showBookmarks.value = false
  if (chapter.value && chapter.value.chapter_index === b.chapter_index) {
    page.value = Math.min(b.page_index, pages.value - 1)
    updatePageUI()
  } else {
    loadChapter(b.chapter_index, b.page_index)
  }
}

async function removeBookmark(b: BookmarkItem): Promise<void> {
  try {
    await api(`/bookmarks/${b.id}`, { method: 'DELETE' })
    bookmarks.value = bookmarks.value.filter(x => x.id !== b.id)
    toast('已删除书签', 'ok')
  } catch (err) {
    toast('删除失败：' + apiErrorMessage(err))
  }
}
</script>

<template>
  <div>
  <div class="p-6 lg:p-8 max-w-7xl mx-auto">
    <!-- 顶部：选书 + 章节切换 -->
    <div class="flex flex-wrap items-center gap-3 mb-4">
      <div class="relative">
        <select :value="bookId || ''" @change="onSelectChange"
          class="appearance-none pl-4 pr-9 py-2.5 rounded-2xl bg-white border border-neutral-200 outline-none text-sm focus:border-accent-500 cursor-pointer">
          <option :value="''" disabled>{{ isPersonal
            ? (personalBooks.length ? '我的上传...' : '暂无个人书籍，去「我的上传」导入')
            : (myBooks.length ? '我的书单...' : '暂无书单，去书库挑一本吧') }}</option>
          <option v-for="b in selectList" :key="b.id" :value="b.id">{{ b.title }}</option>
        </select>
        <i class="fa fa-angle-down absolute right-3.5 top-1/2 -translate-y-1/2 text-soft pointer-events-none"></i>
      </div>
      <div v-if="book" class="text-xs text-soft">{{ bookMetaLine }}</div>
      <div class="ml-auto flex items-center gap-2">
        <button @click="prevChapter" :disabled="!chapter || chapter.chapter_index <= 1"
          class="px-4 py-2.5 rounded-2xl bg-white border border-neutral-200 text-sm hover:border-accent-400 transition disabled:opacity-40">
          <i class="fa fa-arrow-left mr-1"></i>上一章
        </button>
        <button @click="nextChapter" :disabled="!chapter || chapter.chapter_index >= chapters.length"
          class="px-4 py-2.5 rounded-2xl bg-accent-500 text-white text-sm font-semibold hover:bg-accent-600 transition disabled:opacity-40">
          下一章<i class="fa fa-arrow-right ml-1"></i>
        </button>
      </div>
    </div>

    <!-- 章节目录（单行横滚） -->
    <div v-if="chapters.length" class="rounded-2xl bg-white border border-neutral-100 px-4 py-3 mb-4 flex items-center gap-3">
      <span class="text-xs font-semibold text-soft shrink-0"><i class="fa fa-list mr-1"></i>章节</span>
      <div class="flex flex-nowrap gap-2 overflow-x-auto no-scrollbar">
        <button v-for="c in chapters" :key="c.chapter_index"
          @click="loadChapter(c.chapter_index)"
          class="shrink-0 whitespace-nowrap px-3 py-1.5 rounded-lg text-xs border transition"
          :class="chapter && chapter.chapter_index === c.chapter_index
            ? 'bg-accent-50 border-accent-400 text-accent-600 font-semibold'
            : 'border-neutral-200 text-neutral-500 hover:border-accent-400'">
          {{ c.chapter_index }}. {{ c.title }}
        </button>
      </div>
      <button v-if="bookmarks.length" @click="showBookmarks = !showBookmarks"
        class="shrink-0 px-3 py-1.5 rounded-lg text-xs border transition whitespace-nowrap"
        :class="showBookmarks
          ? 'bg-accent-50 border-accent-400 text-accent-600 font-semibold'
          : 'border-neutral-200 text-neutral-500 hover:border-accent-400'">
        <i class="fa fa-bookmark mr-1"></i>书签 {{ bookmarks.length }}
      </button>
    </div>

    <!-- 个人书籍 AI 辅助状态条：水平 / 难度 / 任务进度（静默失败，不阻断阅读） -->
    <div v-if="isPersonal && bookId"
      class="rounded-2xl bg-white border border-neutral-100 px-4 py-2.5 mb-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs">
      <span class="text-soft">我的水平
        <b class="text-ink">{{ myLevel || 'B1' }}</b>
        <span class="ml-1 px-1.5 py-0.5 rounded font-semibold"
          :class="myLevel ? 'bg-green-50 text-green-600' : 'bg-neutral-100 text-neutral-400'">
          {{ myLevel ? '正式测试' : '默认估算' }}
        </span>
      </span>
      <span class="text-soft">全书难度
        <b v-if="analysisReport" class="text-ink">{{ analysisReport.overall_level }} · {{ analysisReport.difficulty_score }} 分</b>
        <b v-else class="text-neutral-400">—</b>
      </span>
      <span v-if="analysisStatus" class="text-soft">
        分析
        <template v-if="['pending', 'running'].includes(analysisStatus.status)">
          <i class="fa fa-circle-o-notch fa-spin text-accent-500 mx-0.5"></i>
          <b class="text-ink">{{ analysisStatus.completed_chapters }}/{{ analysisStatus.total_chapters }} 章</b>
        </template>
        <b v-else-if="analysisStatus.status === 'completed'" class="text-green-600">已完成</b>
        <b v-else-if="analysisStatus.status === 'failed'" class="text-red-500">失败（不影响阅读）</b>
        <b v-else class="text-neutral-400">已取消</b>
      </span>
      <span v-else class="text-soft">分析<b class="text-neutral-400">未生成</b></span>
      <span v-if="predictionLoading" class="text-soft"><i class="fa fa-circle-o-notch fa-spin text-accent-500 mr-1"></i>预测中</span>
      <span v-else-if="predictionError" class="text-red-500">
        <i class="fa fa-exclamation-circle mr-1"></i>生词预测加载失败
        <button @click="retryPrediction" class="underline text-accent-600 ml-0.5">重试</button>
      </span>
      <span class="ml-auto text-soft hidden md:flex items-center gap-2">
        <span class="inline-block w-3.5 border-b-2 border-dotted border-accent-500"></span>预测生词
        <span class="inline-block w-3.5 border-b-2 border-dotted border-emerald-500"></span>已收藏
        <span class="inline-block w-4 h-3 rounded-sm bg-amber-200/70"></span>长难句
      </span>
    </div>

    <!-- 阅读框 -->
    <div class="rounded-3xl bg-white border border-neutral-100 shadow-card flex flex-col overflow-hidden relative" :style="{ height: shellHeight }">
      <!-- 书签列表面板 -->
      <BookmarkPanel v-if="showBookmarks" :bookmarks="bookmarks"
        @close="showBookmarks = false" @jump="jumpToBookmark" @remove="removeBookmark" />
      <!-- 空态 -->
      <div v-if="!bookId && !loadingChapter" class="flex-1 flex-col items-center justify-center text-soft flex">
        <i class="fa fa-book text-4xl opacity-30"></i>
        <p class="mt-4 text-sm">{{ isPersonal ? '从「我的上传」导入一本 EPUB / TXT 开始阅读' : '从书库挑一本书，开始阅读吧' }}</p>
        <button @click="router.push(isPersonal ? { name: 'upload' } : { name: 'library' })"
          class="mt-4 px-5 py-2 rounded-full bg-accent-500 text-white text-xs font-semibold hover:bg-accent-600 transition">
          <i class="fa mr-1.5" :class="isPersonal ? 'fa-cloud-upload' : 'fa-th-large'"></i>{{ isPersonal ? '去上传书籍' : '去书库选书' }}
        </button>
      </div>
      <!-- 加载中 -->
      <div v-else-if="loadingChapter" class="flex-1 flex items-center justify-center text-soft text-sm">
        <i class="fa fa-circle-o-notch fa-spin mr-2"></i>加载中...
      </div>
      <!-- 加载失败：可重试 -->
      <div v-else-if="chapterError" class="flex-1 flex-col items-center justify-center text-soft flex">
        <i class="fa fa-exclamation-triangle text-4xl opacity-30"></i>
        <p class="mt-4 text-sm">章节加载失败：{{ chapterError }}</p>
        <button @click="retryChapter"
          class="mt-4 px-5 py-2 rounded-full bg-accent-500 text-white text-xs font-semibold hover:bg-accent-600 transition">
          <i class="fa fa-refresh mr-1.5"></i>重试
        </button>
      </div>

      <!-- 正文 -->
      <template v-else-if="chapter">
        <div class="flex items-center justify-between flex-wrap gap-2 px-8 lg:px-10 pt-6 pb-4 border-b border-neutral-50">
          <div>
            <div class="text-xs text-soft">{{ book?.title }}</div>
            <h1 class="text-xl lg:text-2xl font-extrabold mt-1">第 {{ chapter.chapter_index }} 章 {{ chapter.title }}</h1>
          </div>
          <div class="ml-auto flex items-center gap-2">
            <button v-if="!isPersonal" @click="toggleBookmark" :title="pageBookmarked ? '移除本页书签' : '给本页加书签'"
              class="px-2.5 sm:px-3 py-1.5 rounded-xl border text-xs font-medium transition"
              :class="pageBookmarked
                ? 'bg-accent-50 border-accent-400 text-accent-600'
                : 'bg-white border-neutral-200 text-neutral-500 hover:border-accent-400 hover:text-accent-600'">
              <i class="fa" :class="pageBookmarked ? 'fa-bookmark' : 'fa-bookmark-o'"></i><span class="hidden sm:inline ml-1.5">书签</span>
            </button>
            <button v-if="!isPersonal" @click="toggleLike"
              class="px-2.5 sm:px-3 py-1.5 rounded-xl border text-xs font-medium transition"
              :class="liked
                ? 'bg-accent-50 border-accent-400 text-accent-600'
                : 'bg-white border-neutral-200 text-neutral-500 hover:border-accent-400 hover:text-accent-600'">
              <i class="fa" :class="liked ? 'fa-heart' : 'fa-heart-o'"></i><span class="hidden sm:inline ml-1.5">点赞</span>
              <span class="sm:hidden ml-1">{{ likeCount }}</span>
            </button>
            <button v-if="!isPersonal" @click="toggleFavorite"
              class="px-3 py-1.5 rounded-xl border text-xs font-medium transition"
              :class="favorited
                ? 'bg-accent-50 border-accent-400 text-accent-600'
                : 'bg-white border-neutral-200 text-neutral-500 hover:border-accent-400 hover:text-accent-600'">
              <i class="fa mr-1.5" :class="favorited ? 'fa-star' : 'fa-star-o'"></i>收藏 {{ favCount }}
            </button>
            <span class="bg-accent-50 text-accent-600 px-3 py-1 rounded-lg text-xs font-medium">{{ chapter.word_count }} 词</span>
          </div>
        </div>

        <div ref="pagesShell" class="flex-1 min-h-0 px-8 lg:px-10 pt-6 pb-14 overflow-hidden bg-[#FBF9F3]"
          @click="onContentClick" @touchstart.passive="onTouchStart" @touchend.passive="onTouchEnd">
          <div ref="pagesInner" class="prose-book text-[17px] text-ink will-change-transform h-full">
            <!-- 正文段落：个人书预测高亮在数据层切片后由 Vue 渲染，不改 DOM 不碰 HTML 字符串 -->
            <p v-for="(p, i) in displayParas" :key="i"><template v-for="(s, j) in p.segs" :key="j"><span
              :data-era-word="s.word?.word || undefined"
              :data-era-sentence="s.sentence ? '1' : undefined"
              :class="{ 'pred-word': !!s.word, 'pred-saved': !!s.word && isWordSaved(s.word.word), 'pred-sentence': !!s.sentence }"
            >{{ s.text }}</span></template></p>

            <!-- 章末过渡页：翻到末页后引导进入下一章，替代硬跳章 -->
            <div class="chapter-end flex flex-col items-center justify-center text-center gap-4 mt-12 py-10">
              <div class="text-[11px] tracking-[0.35em] text-soft">本 章 完</div>
              <div class="h-px w-14 bg-neutral-300"></div>
              <template v-if="nextChapterTitle">
                <div class="text-xs text-soft">下一章</div>
                <button @click="nextChapter"
                  class="px-7 py-3 rounded-full bg-accent-500 text-white text-sm font-semibold hover:bg-accent-600 transition shadow-[0_10px_24px_rgba(255,107,44,.35)]">
                  {{ nextChapterTitle }} <i class="fa fa-arrow-right ml-1.5"></i>
                </button>
              </template>
              <template v-else>
                <div class="book-title text-lg font-bold">The End</div>
                <p class="text-xs text-soft">全书已读完，为你鼓掌 🎉</p>
                <button @click="router.push('/')"
                  class="px-7 py-3 rounded-full bg-ink text-white text-sm font-semibold hover:bg-ink-700 transition">
                  <i class="fa fa-th-large mr-1.5"></i>回到书库
                </button>
              </template>
            </div>
          </div>
        </div>

        <!-- 悬浮翻页条 -->
        <div class="absolute inset-x-0 bottom-0 px-8 lg:px-10 py-3 flex items-center justify-between text-sm bg-gradient-to-t from-white via-white/90 to-transparent pointer-events-none">
          <button @click="prevPage" :disabled="page <= 0"
            class="pointer-events-auto px-5 py-2 rounded-full bg-white border border-neutral-100 shadow-card hover:text-accent-600 transition disabled:opacity-40">
            <i class="fa fa-arrow-left mr-1"></i>上一页
          </button>
          <div class="flex flex-col items-center pointer-events-auto">
            <span class="font-semibold text-xs tracking-wide bg-white/95 px-4 py-1.5 rounded-full shadow-card border border-neutral-100">第 {{ page + 1 }} / {{ pages }} 页</span>
            <span class="mt-1 text-[11px] text-soft">第 {{ chapter.chapter_index }} / {{ chapters.length }} 章 · 约 {{ Math.round(percent) }}%</span>
          </div>
          <button @click="nextPage" :disabled="page >= pages - 1 && (!chapter || chapter.chapter_index >= chapters.length)"
            class="pointer-events-auto px-5 py-2 rounded-full bg-accent-500 text-white shadow-card hover:bg-accent-600 transition disabled:opacity-40">
            下一页<i class="fa fa-arrow-right ml-1"></i>
          </button>
        </div>
      </template>
    </div>
  </div>

  <!-- ============ AI 抽屉 ============ -->
  <AiDrawer :open="drawerOpen" :tab="aiTab" :qa-history="qaHistory" :qa-sending="qaSending"
    :translating="translating" :page-translation="pageTranslation"
    @close="drawerOpen = false" @update:tab="aiTab = $event"
    @ask="askQuestion" @translate-page="translatePage" />

  <!-- ============ 点词查义浮层 ============ -->
  <WordLookupPopup v-if="lookup" :lookup="lookup" show-save :prediction="lookupPrediction"
    @close="lookup = null" @save="saveToVocabulary" @remove="removeFromVocabulary" />

  <!-- ============ 划句翻译浮层 ============ -->
  <SelectionTranslatePopup :bar="selBar" :result="selResult" :translating="selTranslating"
    @translate="translateSelection" @close-result="selResult = null" />

  <!-- 悬浮按钮（可拖动 + 位置记忆） -->
  <AiFab v-show="!drawerOpen" @toggle="drawerOpen = !drawerOpen" />
  </div>
</template>

<style scoped>
/* 个人书预测高亮：轻量样式，不改变排版（纯 inline，不影响分页与段落结构） */
.pred-word {
  cursor: pointer;
  border-bottom: 2px dotted rgba(249, 115, 22, 0.55);
  padding-bottom: 1px;
}
.pred-word:hover {
  background: rgba(249, 115, 22, 0.08);
}
/* 生词本已收藏的词：绿色虚线以示区别 */
.pred-word.pred-saved {
  border-bottom-color: rgba(16, 185, 129, 0.6);
  background: rgba(16, 185, 129, 0.07);
}
/* 长难句：淡黄底色 */
.pred-sentence {
  cursor: pointer;
  background: rgba(252, 211, 77, 0.28);
  border-radius: 2px;
}
.pred-sentence:hover {
  background: rgba(252, 211, 77, 0.45);
}
</style>
