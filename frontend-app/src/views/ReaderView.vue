<script setup lang="ts">
// 阅读器：固定高度分页（CSS 多列平移）+ 章节目录 + AI 抽屉（问答 / 翻译本页）+ 可拖动悬浮按钮
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, LAST_BOOK_KEY } from '../api/client'
import { loadBooks, store, toast } from '../store'
import type { Book, BookmarkItem, BookInteraction, Chapter, ChapterMeta, QAItem, ReadingProgress, WordLookup } from '../types'

const route = useRoute()
const router = useRouter()

const bookId = ref<number | null>(null)
const chapters = ref<ChapterMeta[]>([])
const chapter = ref<(Chapter & { word_count: number }) | null>(null)
const loadingChapter = ref(false)

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
const qaInput = ref('')
const qaSending = ref(false)
const qaList = ref<HTMLElement | null>(null)
const translating = ref(false)
const pageTranslation = ref('')

const shellHeight = 'max(480px, calc(100vh - 200px))' // 矮视口下保底高度，避免每列字数过少

const book = computed<Book | null>(() => store.books.find(b => b.id === bookId.value) || null)
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

onMounted(async () => {
  try {
    await loadBooks()
  } catch (err) {
    toast('书库加载失败：' + (err as Error).message)
  }
  await loadMyBooks()
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
  if (!id) return
  // 当前书保证出现在下拉里（首次从书库进入时可能还没有互动记录）
  if (!myBooks.value.some(b => b.id === id)) {
    const b = store.books.find(x => x.id === id)
    if (b) myBooks.value = [...myBooks.value, b]
  }
  try {
    chapters.value = await api<ChapterMeta[]>(`/books/${id}/chapters`)
    // 未指定章节：优先服务端进度（章节 + 页内断点），兜底第 1 章
    let resumePage = 0
    if (!chapterIndex || chapterIndex < 1) {
      try {
        const p = await api<ReadingProgress>(`/reading/progress/${id}`)
        chapterIndex = Math.min(p.chapter_index, chapters.value.length) || 1
        resumePage = p.page_index || 0
      } catch {
        chapterIndex = 1
      }
    }
    await loadChapter(chapterIndex, resumePage)
    loadInteraction() // 点赞/收藏状态与计数（失败静默）
    loadBookmarks() // 书签列表（失败静默）
  } catch (err) {
    toast('章节目录加载失败：' + (err as Error).message)
  }
}

function onSelectChange(e: Event): void {
  const id = parseInt((e.target as HTMLSelectElement).value)
  if (id) router.replace({ name: 'reader', params: { bookId: String(id) } })
  onBookChange(id)
}

// ================= 章节加载 =================
async function loadChapter(index: number, startPage = 0): Promise<void> {
  if (!chapters.value.length || !bookId.value) return
  index = Math.max(1, Math.min(index, chapters.value.length))
  loadingChapter.value = true
  try {
    const data = await api<Chapter & { word_count: number }>(`/books/${bookId.value}/chapters/${index}`)
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
    localStorage.setItem(LAST_BOOK_KEY, JSON.stringify({
      book_id: bookId.value, chapter_index: data.chapter_index, percent: percent.value,
    }))
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (err) {
    toast('章节加载失败：' + (err as Error).message)
  } finally {
    loadingChapter.value = false
  }
}

async function saveProgress(): Promise<void> {
  if (!chapter.value || !bookId.value) return
  try {
    await api(`/reading/progress/${bookId.value}`, {
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
  if (!bookId.value || !chapter.value) return
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
    toast('操作失败：' + (err as Error).message)
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
    toast('操作失败：' + (err as Error).message)
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
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  document.removeEventListener('keydown', onKeydown)
  document.removeEventListener('selectionchange', onSelectionChange)
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
    toast('翻译失败：' + (err as Error).message)
  } finally {
    translating.value = false
  }
}

// ================= AI 问答（RAG，限定当前章节） =================
async function askQuestion(): Promise<void> {
  if (!chapter.value || !bookId.value) { toast('请先选择一本书和章节'); return }
  const question = qaInput.value.trim()
  if (!question || qaSending.value) return
  qaSending.value = true
  qaHistory.value.push({ role: 'me', text: question })
  qaInput.value = ''
  try {
    const result = await api<{ answer: string; scope: string }>('/ask/reading', {
      method: 'POST',
      body: { book_id: bookId.value, chapter_index: chapter.value.chapter_index, question },
    })
    qaHistory.value.push({ role: 'ai', text: result.answer, scope: result.scope })
  } catch (err) {
    qaHistory.value.push({ role: 'err', text: '回答失败：' + (err as Error).message })
  } finally {
    qaSending.value = false
    await nextTick()
    if (qaList.value) qaList.value.scrollTop = qaList.value.scrollHeight
  }
}

function scopeLabel(scope: string | undefined): string | null {
  if (scope === 'chapter') return '依据：本章内容'
  if (scope === 'book') return '依据：本章 + 全书检索'
  if (scope === 'none') return '未找到相关依据'
  return null
}

// ================= 点词查义（点击正文单词弹出释义卡片） =================
interface LookupPop {
  word: string
  sentence: string
  x: number
  y: number
  loading: boolean
  data: WordLookup | null
  error: string
  saved: boolean
}

const lookup = ref<LookupPop | null>(null)
const savedWords = new Set<string>() // 本次会话已收录的词（提示口径用）

// 定位点击处的单词与其所在句子（caretRangeFromPoint 兼容 Chrome/Safari，Firefox 走 caretPositionFromPoint）
function extractWordAt(x: number, y: number): { word: string; sentence: string } | null {
  const doc = document as Document & {
    caretRangeFromPoint?: (x: number, y: number) => Range | null
    caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null
  }
  let node: Node | null = null
  let offset = 0
  if (doc.caretRangeFromPoint) {
    const r = doc.caretRangeFromPoint(x, y)
    node = r?.startContainer ?? null
    offset = r?.startOffset ?? 0
  } else if (doc.caretPositionFromPoint) {
    const p = doc.caretPositionFromPoint(x, y)
    node = p?.offsetNode ?? null
    offset = p?.offset ?? 0
  }
  if (!node || node.nodeType !== Node.TEXT_NODE) return null
  const text = node.textContent || ''
  if (offset >= text.length) return null
  const isWordChar = (ch: string): boolean => /[A-Za-z'-]/.test(ch)
  if (!isWordChar(text[offset])) return null
  let s = offset
  let e = offset
  while (s > 0 && isWordChar(text[s - 1])) s--
  while (e < text.length && isWordChar(text[e])) e++
  const word = text.slice(s, e)
  if (word.length < 2 || word.length > 40) return null
  // 句子边界：向前找句号/问号/叹号，向后找句末标点
  let ss = Math.max(text.lastIndexOf('. ', e), text.lastIndexOf('! ', e), text.lastIndexOf('? ', e), text.lastIndexOf('." ', e)) + 1
  if (ss >= e) ss = 0
  let se = text.length
  for (const mark of ['. ', '! ', '? ', '." ']) {
    const i = text.indexOf(mark, e)
    if (i !== -1 && i < se) se = i + mark.length
  }
  const sentence = text.slice(ss, se).trim().slice(0, 400)
  return { word, sentence }
}

async function onContentClick(e: MouseEvent): Promise<void> {
  selResult.value = null
  if (window.getSelection()?.toString()) return // 划词中不触发点词
  const target = e.target as HTMLElement
  if (!target.closest('p')) return // 只对正文段落生效（章末按钮等不受影响）
  const hit = extractWordAt(e.clientX, e.clientY)
  if (!hit || !bookId.value || !chapter.value) return
  const word = hit.word.toLowerCase()
  const POP_W = 288
  const x = Math.min(Math.max(8, e.clientX - POP_W / 2), window.innerWidth - POP_W - 12)
  const y = Math.min(e.clientY + 16, window.innerHeight - 300)
  lookup.value = {
    word, sentence: hit.sentence, x, y,
    loading: true, data: null, error: '', saved: savedWords.has(word),
  }
  try {
    const data = await api<WordLookup>(`/lookup/word/${encodeURIComponent(word)}`)
    if (lookup.value && lookup.value.word === word) lookup.value.data = data
  } catch (err) {
    if (lookup.value && lookup.value.word === word) lookup.value.error = (err as Error).message
  } finally {
    if (lookup.value && lookup.value.word === word) lookup.value.loading = false
  }
}

async function saveToVocabulary(): Promise<void> {
  const l = lookup.value
  if (!l || !bookId.value || !chapter.value || l.saved) return
  try {
    await api('/vocabulary', {
      method: 'POST',
      body: {
        word: l.word, book_id: bookId.value,
        chapter_index: chapter.value.chapter_index,
        context_sentence: l.sentence || null,
      },
    })
    savedWords.add(l.word)
    l.saved = true
    toast('已收录到生词本', 'success')
  } catch (err) {
    toast('收录失败：' + (err as Error).message)
  }
}

// ================= 划句翻译（选中正文句子浮现翻译按钮） =================
const selBar = ref<{ x: number; y: number; text: string } | null>(null)
const selResult = ref<{ x: number; y: number; text: string } | null>(null)
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
    selResult.value = { x, y, text: '翻译失败：' + (err as Error).message }
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
    toast('书签操作失败：' + (err as Error).message)
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
    toast('删除失败：' + (err as Error).message)
  }
}

// ================= 悬浮按钮拖动（位置记忆） =================
const fab = ref<HTMLElement | null>(null)
const fabStyle = ref<Record<string, string>>({})
let dragMoved = false
let drag: { sx: number; sy: number; ox: number; oy: number } | null = null
const FAB_POS_KEY = 'era_ai_fab_pos'

function onFabPointerDown(e: PointerEvent): void {
  const r = fab.value!.getBoundingClientRect()
  drag = { sx: e.clientX, sy: e.clientY, ox: r.left, oy: r.top }
  fab.value!.setPointerCapture(e.pointerId)
}

function onFabPointerMove(e: PointerEvent): void {
  if (!drag) return
  const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy
  if (Math.abs(dx) + Math.abs(dy) > 6) {
    dragMoved = true
    const x = Math.min(Math.max(8, drag.ox + dx), window.innerWidth - fab.value!.offsetWidth - 8)
    const y = Math.min(Math.max(8, drag.oy + dy), window.innerHeight - fab.value!.offsetHeight - 8)
    fabStyle.value = { left: x + 'px', top: y + 'px' }
  }
}

function onFabPointerUp(): void {
  if (dragMoved) {
    localStorage.setItem(FAB_POS_KEY, JSON.stringify({ x: fab.value!.offsetLeft, y: fab.value!.offsetTop }))
  }
  drag = null
}

function onFabClick(): void {
  if (dragMoved) { dragMoved = false; return }
  drawerOpen.value = !drawerOpen.value
}

onMounted(() => {
  try {
    const saved = JSON.parse(localStorage.getItem(FAB_POS_KEY) || 'null')
    if (saved && typeof saved.x === 'number') fabStyle.value = { left: saved.x + 'px', top: saved.y + 'px' }
  } catch { /* 位置数据损坏则忽略 */ }
})
</script>

<template>
  <div>
  <div class="p-6 lg:p-8 max-w-7xl mx-auto">
    <!-- 顶部：选书 + 章节切换 -->
    <div class="flex flex-wrap items-center gap-3 mb-4">
      <div class="relative">
        <select :value="bookId || ''" @change="onSelectChange"
          class="appearance-none pl-4 pr-9 py-2.5 rounded-2xl bg-white border border-neutral-200 outline-none text-sm focus:border-accent-500 cursor-pointer">
          <option :value="''" disabled>{{ myBooks.length ? '我的书单...' : '暂无书单，去书库挑一本吧' }}</option>
          <option v-for="b in myBooks" :key="b.id" :value="b.id">{{ b.title }}</option>
        </select>
        <i class="fa fa-angle-down absolute right-3.5 top-1/2 -translate-y-1/2 text-soft pointer-events-none"></i>
      </div>
      <div v-if="book" class="text-xs text-soft">{{ book.author }} · {{ book.year }}{{ book.word_count ? ` · ${(book.word_count / 10000).toFixed(1)} 万词` : '' }}</div>
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

    <!-- 阅读框 -->
    <div class="rounded-3xl bg-white border border-neutral-100 shadow-card flex flex-col overflow-hidden relative" :style="{ height: shellHeight }">
      <!-- 书签列表面板（本页书签可移除，其他页书签可跳转） -->
      <div v-if="showBookmarks" class="absolute top-16 right-4 z-30 w-80 max-w-[85%] max-h-[70%] overflow-y-auto rounded-2xl bg-white border border-neutral-200 shadow-float p-3">
        <div class="flex items-center justify-between px-1 pb-2">
          <span class="text-xs font-bold text-ink"><i class="fa fa-bookmark mr-1 text-accent-500"></i>本书书签（{{ bookmarks.length }}）</span>
          <button @click="showBookmarks = false" class="w-7 h-7 rounded-lg hover:bg-neutral-100 text-soft transition"><i class="fa fa-close text-xs"></i></button>
        </div>
        <div v-if="!bookmarks.length" class="px-1 py-4 text-xs text-soft">还没有书签，点击顶部「书签」按钮收藏当前页</div>
        <div v-for="b in bookmarks" :key="b.id"
          class="group flex items-start gap-2 p-2.5 rounded-xl hover:bg-neutral-50 transition cursor-pointer"
          @click="jumpToBookmark(b)">
          <i class="fa fa-bookmark text-accent-400 text-xs mt-1 shrink-0"></i>
          <div class="min-w-0 flex-1">
            <div class="text-[11px] text-soft">第 {{ b.chapter_index }} 章 · 第 {{ b.page_index + 1 }} 页</div>
            <div class="text-xs text-ink leading-5 line-clamp-2">{{ b.excerpt || '（无摘要）' }}</div>
          </div>
          <button @click.stop="removeBookmark(b)"
            title="删除书签"
            class="shrink-0 w-7 h-7 rounded-lg text-neutral-300 hover:text-red-500 hover:bg-red-50 transition">
            <i class="fa fa-trash text-xs"></i>
          </button>
        </div>
      </div>
      <!-- 空态 -->
      <div v-if="!bookId && !loadingChapter" class="flex-1 flex-col items-center justify-center text-soft flex">
        <i class="fa fa-book text-4xl opacity-30"></i>
        <p class="mt-4 text-sm">从书库挑一本书，开始阅读吧</p>
        <button @click="router.push('/')"
          class="mt-4 px-5 py-2 rounded-full bg-accent-500 text-white text-xs font-semibold hover:bg-accent-600 transition">
          <i class="fa fa-th-large mr-1.5"></i>去书库选书
        </button>
      </div>
      <!-- 加载中 -->
      <div v-else-if="loadingChapter" class="flex-1 flex items-center justify-center text-soft text-sm">
        <i class="fa fa-circle-o-notch fa-spin mr-2"></i>加载中...
      </div>

      <!-- 正文 -->
      <template v-else-if="chapter">
        <div class="flex items-center justify-between flex-wrap gap-2 px-8 lg:px-10 pt-6 pb-4 border-b border-neutral-50">
          <div>
            <div class="text-xs text-soft">{{ book?.title }}</div>
            <h1 class="text-xl lg:text-2xl font-extrabold mt-1">第 {{ chapter.chapter_index }} 章 {{ chapter.title }}</h1>
          </div>
          <div class="ml-auto flex items-center gap-2">
            <button @click="toggleBookmark" :title="pageBookmarked ? '移除本页书签' : '给本页加书签'"
              class="px-2.5 sm:px-3 py-1.5 rounded-xl border text-xs font-medium transition"
              :class="pageBookmarked
                ? 'bg-accent-50 border-accent-400 text-accent-600'
                : 'bg-white border-neutral-200 text-neutral-500 hover:border-accent-400 hover:text-accent-600'">
              <i class="fa" :class="pageBookmarked ? 'fa-bookmark' : 'fa-bookmark-o'"></i><span class="hidden sm:inline ml-1.5">书签</span>
            </button>
            <button @click="toggleLike"
              class="px-2.5 sm:px-3 py-1.5 rounded-xl border text-xs font-medium transition"
              :class="liked
                ? 'bg-accent-50 border-accent-400 text-accent-600'
                : 'bg-white border-neutral-200 text-neutral-500 hover:border-accent-400 hover:text-accent-600'">
              <i class="fa" :class="liked ? 'fa-heart' : 'fa-heart-o'"></i><span class="hidden sm:inline ml-1.5">点赞</span>
              <span class="sm:hidden ml-1">{{ likeCount }}</span>
            </button>
            <button @click="toggleFavorite"
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
          @click="onContentClick">
          <div ref="pagesInner" class="prose-book text-[17px] text-ink will-change-transform h-full">
            <p v-for="(p, i) in chapter.content.split(/\n\s*\n/).filter(s => s.trim())" :key="i">{{ p.trim() }}</p>

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
  <div class="fixed inset-y-0 right-0 w-[380px] max-w-[92vw] bg-white shadow-float z-50 flex flex-col transition-transform duration-300"
    :class="drawerOpen ? 'translate-x-0' : 'translate-x-full'">
    <div class="p-5 border-b border-neutral-100 flex items-center justify-between">
      <div class="font-bold text-sm">AI 助手 <span class="text-[11px] text-soft font-normal">基于本章内容（RAG）</span></div>
      <button @click="drawerOpen = false" class="w-8 h-8 rounded-lg hover:bg-neutral-100 text-soft transition">
        <i class="fa fa-close"></i>
      </button>
    </div>

    <div class="flex border-b border-neutral-100 text-sm">
      <button @click="aiTab = 'qa'" class="flex-1 py-3 font-semibold border-b-2 transition"
        :class="aiTab === 'qa' ? 'text-accent-600 border-accent-500' : 'text-soft border-transparent hover:text-accent-500'">
        AI 问答
      </button>
      <button @click="aiTab = 'tr'" class="flex-1 py-3 font-semibold border-b-2 transition"
        :class="aiTab === 'tr' ? 'text-accent-600 border-accent-500' : 'text-soft border-transparent hover:text-accent-500'">
        翻译本页
      </button>
    </div>

    <!-- 问答面板 -->
    <div v-show="aiTab === 'qa'" class="flex-1 min-h-0 flex flex-col">
      <div ref="qaList" class="flex-1 overflow-y-auto p-5 space-y-3">
        <p v-if="!qaHistory.length" class="text-xs text-soft leading-6">
          先选择书和章节，再提问效果最好。<br>例如：「这一章发生了什么？」「主人公为什么离开？」
        </p>
        <template v-for="(m, i) in qaHistory" :key="i">
          <div v-if="m.role === 'me'" class="p-3 rounded-2xl rounded-br-md bg-accent-50 text-sm ml-8">{{ m.text }}</div>
          <div v-else-if="m.role === 'ai'" class="mr-8">
            <div class="p-3 rounded-2xl rounded-bl-md bg-neutral-50 border border-neutral-100 text-sm whitespace-pre-line leading-7">{{ m.text }}</div>
            <div v-if="scopeLabel(m.scope)" class="px-1 pt-1 text-[11px] text-soft">
              <i class="fa fa-search mr-1"></i>{{ scopeLabel(m.scope) }}
            </div>
          </div>
          <div v-else class="p-3 rounded-2xl bg-red-50 text-sm text-red-600 mr-8">{{ m.text }}</div>
        </template>
        <div v-if="qaSending" class="p-3 rounded-2xl bg-neutral-50 text-sm text-soft mr-8 w-fit">
          <i class="fa fa-circle-o-notch fa-spin mr-1"></i>AI 思考中...
        </div>
      </div>
      <div class="p-4 border-t border-neutral-100 flex gap-2">
        <input v-model="qaInput" @keydown.enter="askQuestion" placeholder="就本章内容提问..."
          class="flex-1 px-3.5 py-2.5 rounded-2xl bg-neutral-50 border border-neutral-200 focus:border-accent-500 outline-none text-sm" />
        <button @click="askQuestion" :disabled="qaSending"
          class="px-4 rounded-2xl bg-accent-500 text-white text-sm hover:bg-accent-600 transition disabled:opacity-60">
          <i class="fa fa-send"></i>
        </button>
      </div>
    </div>

    <!-- 翻译面板 -->
    <div v-show="aiTab === 'tr'" class="flex-1 min-h-0 flex flex-col p-5 overflow-y-auto">
      <button @click="translatePage" :disabled="translating"
        class="w-full py-2.5 rounded-2xl bg-accent-500 text-white text-sm font-semibold hover:bg-accent-600 transition disabled:opacity-60">
        <i v-if="translating" class="fa fa-circle-o-notch fa-spin mr-1"></i>
        <i v-else class="fa fa-language mr-1"></i>
        {{ translating ? '翻译中，约需十几秒...' : '翻译本页' }}
      </button>
      <div v-if="pageTranslation" class="mt-4 p-4 rounded-2xl bg-accent-50 border border-accent-100 text-sm leading-7 whitespace-pre-line">{{ pageTranslation }}</div>
    </div>
  </div>

  <!-- ============ 点词查义浮层 ============ -->
  <div v-if="lookup" class="fixed z-[60] w-72 rounded-2xl bg-white border border-neutral-200 shadow-float p-4"
    :style="{ left: lookup.x + 'px', top: lookup.y + 'px' }">
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0">
        <div class="book-title text-lg font-bold leading-tight">{{ lookup.word }}</div>
        <div v-if="lookup.data?.phonetic" class="text-xs text-soft mt-0.5">{{ lookup.data.phonetic }}</div>
      </div>
      <button @click="lookup = null" class="shrink-0 w-7 h-7 rounded-lg hover:bg-neutral-100 text-soft transition">
        <i class="fa fa-close text-xs"></i>
      </button>
    </div>
    <!-- 加载中 -->
    <div v-if="lookup.loading" class="py-4 text-sm text-soft">
      <i class="fa fa-circle-o-notch fa-spin mr-1"></i>查询释义中...
    </div>
    <!-- 查询失败 -->
    <div v-else-if="lookup.error" class="py-3 text-sm text-red-500">
      <i class="fa fa-exclamation-circle mr-1"></i>{{ lookup.error }}
    </div>
    <!-- 释义 -->
    <template v-else-if="lookup.data">
      <ul class="mt-2 space-y-1.5">
        <li v-for="(s, i) in lookup.data.senses" :key="i" class="text-sm text-ink leading-6">
          <span class="text-accent-500 mr-1">·</span>{{ s }}
        </li>
      </ul>
      <div v-if="lookup.data.example_en" class="mt-3 p-2.5 rounded-xl bg-neutral-50 text-xs leading-5">
        <p class="text-ink">{{ lookup.data.example_en }}</p>
        <p v-if="lookup.data.example_cn" class="text-soft mt-1">{{ lookup.data.example_cn }}</p>
      </div>
      <button @click="saveToVocabulary" :disabled="lookup.saved"
        class="mt-3 w-full py-2 rounded-xl text-xs font-semibold transition"
        :class="lookup.saved
          ? 'bg-emerald-50 text-emerald-600 cursor-default'
          : 'bg-accent-500 text-white hover:bg-accent-600'">
        <i class="fa mr-1.5" :class="lookup.saved ? 'fa-check' : 'fa-plus'"></i>
        {{ lookup.saved ? '已在生词本中' : '收录到生词本' }}
      </button>
    </template>
  </div>

  <!-- ============ 划句翻译浮层 ============ -->
  <div v-if="selBar" class="fixed z-[60] -translate-x-1/2 flex rounded-full bg-ink text-white shadow-float overflow-hidden"
    :style="{ left: selBar.x + 'px', top: selBar.y + 'px' }">
    <button @click="translateSelection" class="px-4 py-2 text-xs font-medium hover:bg-ink-700 transition whitespace-nowrap">
      <i class="fa fa-language mr-1 text-accent-400"></i>翻译这句话
    </button>
  </div>
  <div v-if="selResult" class="fixed z-[60] -translate-x-1/2 w-80 max-w-[90vw] rounded-2xl bg-white border border-neutral-200 shadow-float p-4"
    :style="{ left: selResult.x + 'px', top: selResult.y + 'px' }">
    <div class="flex items-start justify-between gap-2">
      <span class="text-[11px] font-bold text-soft shrink-0"><i class="fa fa-language mr-1 text-accent-500"></i>译文</span>
      <button @click="selResult = null" class="shrink-0 w-7 h-7 rounded-lg hover:bg-neutral-100 text-soft transition">
        <i class="fa fa-close text-xs"></i>
      </button>
    </div>
    <div v-if="selTranslating" class="py-2 text-sm text-soft"><i class="fa fa-circle-o-notch fa-spin mr-1"></i>翻译中...</div>
    <p v-else class="text-sm text-ink leading-7 whitespace-pre-line">{{ selResult.text }}</p>
  </div>

  <!-- 悬浮按钮（可拖动 + 位置记忆） -->
  <button v-show="!drawerOpen" ref="fab" @click="onFabClick"
    @pointerdown="onFabPointerDown" @pointermove="onFabPointerMove" @pointerup="onFabPointerUp"
    title="AI 助手（问答 / 翻译），可拖动"
    class="fixed right-6 bottom-8 z-40 w-14 h-14 rounded-full bg-gradient-to-br from-accent-400 to-accent-600 text-white shadow-[0_14px_34px_rgba(255,107,44,.5)] flex items-center justify-center text-xl hover:scale-105 transition"
    :style="{ ...fabStyle, touchAction: 'none', userSelect: 'none', cursor: 'grab' }">
    <i class="fa fa-magic"></i>
  </button>
  </div>
</template>
