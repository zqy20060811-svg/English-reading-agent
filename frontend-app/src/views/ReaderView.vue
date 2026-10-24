<script setup>
// 阅读器：固定高度分页（CSS 多列平移）+ 章节目录 + AI 抽屉（问答 / 翻译本页）+ 可拖动悬浮按钮
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, LAST_BOOK_KEY } from '../api/client'
import { loadBooks, store, toast } from '../store'

const route = useRoute()
const router = useRouter()

const bookId = ref(null)
const chapters = ref([])
const chapter = ref(null)
const loadingChapter = ref(false)

// 分页状态
const PAGE_GAP = 64
const page = ref(0)
const pages = ref(1)
const pagesShell = ref(null)
const pagesInner = ref(null)

// AI 抽屉
const drawerOpen = ref(false)
const aiTab = ref('qa')
const qaHistory = ref([]) // [{ role: 'me'|'ai'|'err', text, scope }]
const qaInput = ref('')
const qaSending = ref(false)
const qaList = ref(null)
const translating = ref(false)
const pageTranslation = ref('')

const shellHeight = 'max(480px, calc(100vh - 200px))' // 矮视口下保底高度，避免每列字数过少

const book = computed(() => store.books.find(b => b.id === bookId.value) || null)
const percent = computed(() =>
  chapter.value && chapters.value.length ? (chapter.value.chapter_index / chapters.value.length) * 100 : 0)

// 下一章标题（章末过渡页用；最后一章为 null）
const nextChapterTitle = computed(() => {
  if (!chapter.value || chapter.value.chapter_index >= chapters.value.length) return null
  const next = chapters.value.find(c => c.chapter_index === chapter.value.chapter_index + 1)
  return next ? `第 ${next.chapter_index} 章 · ${next.title}` : null
})

// ================= 初始化与书目切换 =================

// 我的书单：读过/点赞/收藏过的书（下拉不再展示全库）
const myBooks = ref([])

async function loadMyBooks() {
  try {
    myBooks.value = await api('/books/mine')
  } catch { /* 拉取失败时下拉留空，提示去书库选书 */ }
}

onMounted(async () => {
  try {
    await loadBooks()
  } catch (err) {
    toast('书库加载失败：' + err.message)
  }
  await loadMyBooks()
  const param = parseInt(route.params.bookId)
  if (param) {
    await onBookChange(param, 0) // 0 = 读服务端进度
  }
})

async function onBookChange(id, chapterIndex = 1) {
  bookId.value = id || null
  chapter.value = null
  chapters.value = []
  qaHistory.value = []
  pageTranslation.value = ''
  if (!id) return
  // 当前书保证出现在下拉里（首次从书库进入时可能还没有互动记录）
  if (!myBooks.value.some(b => b.id === id)) {
    const b = store.books.find(x => x.id === id)
    if (b) myBooks.value = [...myBooks.value, b]
  }
  try {
    chapters.value = await api(`/books/${id}/chapters`)
    // 未指定章节：优先服务端进度，兜底第 1 章
    if (!chapterIndex || chapterIndex < 1) {
      try {
        const p = await api(`/reading/progress/${id}`)
        chapterIndex = Math.min(p.chapter_index, chapters.value.length) || 1
      } catch {
        chapterIndex = 1
      }
    }
    await loadChapter(chapterIndex)
    loadInteraction() // 点赞/收藏状态与计数（失败静默）
  } catch (err) {
    toast('章节目录加载失败：' + err.message)
  }
}

function onSelectChange(e) {
  const id = parseInt(e.target.value)
  if (id) router.replace({ name: 'reader', params: { bookId: String(id) } })
  onBookChange(id)
}

// ================= 章节加载 =================
async function loadChapter(index) {
  if (!chapters.value.length || !bookId.value) return
  index = Math.max(1, Math.min(index, chapters.value.length))
  loadingChapter.value = true
  try {
    const data = await api(`/books/${bookId.value}/chapters/${index}`)
    chapter.value = data
    pageTranslation.value = ''
    loadingChapter.value = false // 先退出加载态，正文 DOM 挂载后才能测量分页
    await nextTick()
    await new Promise(r => requestAnimationFrame(r)) // 再等一帧，确保布局完成
    paginate()
    saveProgress()
    localStorage.setItem(LAST_BOOK_KEY, JSON.stringify({
      book_id: bookId.value, chapter_index: data.chapter_index, percent: percent.value,
    }))
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (err) {
    toast('章节加载失败：' + err.message)
  } finally {
    loadingChapter.value = false
  }
}

async function saveProgress() {
  if (!chapter.value || !bookId.value) return
  try {
    await api(`/reading/progress/${bookId.value}`, {
      method: 'PUT',
      body: { chapter_index: chapter.value.chapter_index, char_offset: 0, percent: Math.min(percent.value, 100) },
    })
  } catch { /* 进度保存失败不阻塞阅读 */ }
}

const prevChapter = () => chapter.value && loadChapter(chapter.value.chapter_index - 1)

function reportFinish() {
  // 进入下一章视为读完当前章：上报热度事件（同人同书每日限计 1 次，失败静默）
  if (!bookId.value || !chapter.value) return
  api(`/books/${bookId.value}/events`, {
    method: 'POST',
    body: { event_type: 'finish_chapter' },
  }).catch(() => {})
}

function nextChapter() {
  if (!chapter.value) return
  reportFinish()
  loadChapter(chapter.value.chapter_index + 1)
}

// ================= 点赞 / 收藏（热度行为） =================
const liked = ref(false)
const favorited = ref(false)
const likeCount = ref(0)
const favCount = ref(0)

async function loadInteraction() {
  if (!bookId.value) return
  try {
    const d = await api(`/books/${bookId.value}/hot`)
    liked.value = d.liked
    favorited.value = d.favorited
    likeCount.value = d.like_count
    favCount.value = d.favorite_count
  } catch { /* 热度信息加载失败不阻塞阅读 */ }
}

async function toggleLike() {
  if (!bookId.value) return
  try {
    const d = await api(`/books/${bookId.value}/like`, { method: 'POST' })
    liked.value = d.liked
    likeCount.value = d.like_count
    toast(d.liked ? '已点赞' : '已取消点赞', 'ok')
  } catch (err) {
    toast('操作失败：' + err.message)
  }
}

async function toggleFavorite() {
  if (!bookId.value) return
  try {
    const d = await api(`/books/${bookId.value}/favorite`, { method: 'POST' })
    favorited.value = d.favorited
    favCount.value = d.favorite_count
    toast(d.favorited ? '已加入收藏' : '已取消收藏', 'ok')
  } catch (err) {
    toast('操作失败：' + err.message)
  }
}

// ================= 分页（CSS 多列横向平移） =================
function pageMetrics() {
  const shell = pagesShell.value
  const cs = getComputedStyle(shell)
  const w = shell.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)
  return { w, padL: parseFloat(cs.paddingLeft), padR: parseFloat(cs.paddingRight) }
}

function paginate() {
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

function updatePageUI() {
  const { w } = pageMetrics()
  if (pagesInner.value) pagesInner.value.style.transform = `translateX(-${page.value * (w + PAGE_GAP)}px)`
  // 翻页后旧页译文失效
  pageTranslation.value = ''
}

function prevPage() {
  if (page.value > 0) { page.value--; updatePageUI() }
}

function nextPage() {
  if (page.value < pages.value - 1) { page.value++; updatePageUI() }
  else if (chapter.value && chapter.value.chapter_index < chapters.value.length) nextChapter()
}

let resizeTimer = null
function onResize() {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(paginate, 200)
}

function onKeydown(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
  if (e.key === 'ArrowLeft') prevPage()
  if (e.key === 'ArrowRight') nextPage()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  document.removeEventListener('keydown', onKeydown)
})

// ================= 翻译本页（仅当前可见页） =================
function currentPageText() {
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

async function translatePage() {
  if (!chapter.value) { toast('请先选择一本书'); return }
  const text = currentPageText().slice(0, 4500)
  if (!text.trim()) { toast('当前页没有可翻译的内容'); return }
  translating.value = true
  try {
    const result = await api('/translate', { method: 'POST', body: { text, target_lang: '中文' } })
    pageTranslation.value = result.translation
  } catch (err) {
    toast('翻译失败：' + err.message)
  } finally {
    translating.value = false
  }
}

// ================= AI 问答（RAG，限定当前章节） =================
async function askQuestion() {
  if (!chapter.value || !bookId.value) { toast('请先选择一本书和章节'); return }
  const question = qaInput.value.trim()
  if (!question || qaSending.value) return
  qaSending.value = true
  qaHistory.value.push({ role: 'me', text: question })
  qaInput.value = ''
  try {
    const result = await api('/ask/reading', {
      method: 'POST',
      body: { book_id: bookId.value, chapter_index: chapter.value.chapter_index, question },
    })
    qaHistory.value.push({ role: 'ai', text: result.answer, scope: result.scope })
  } catch (err) {
    qaHistory.value.push({ role: 'err', text: '回答失败：' + err.message })
  } finally {
    qaSending.value = false
    await nextTick()
    if (qaList.value) qaList.value.scrollTop = qaList.value.scrollHeight
  }
}

function scopeLabel(scope) {
  if (scope === 'chapter') return '依据：本章内容'
  if (scope === 'book') return '依据：本章 + 全书检索'
  if (scope === 'none') return '未找到相关依据'
  return null
}

// ================= 悬浮按钮拖动（位置记忆） =================
const fab = ref(null)
const fabStyle = ref({})
let dragMoved = false
let drag = null
const FAB_POS_KEY = 'era_ai_fab_pos'

function onFabPointerDown(e) {
  const r = fab.value.getBoundingClientRect()
  drag = { sx: e.clientX, sy: e.clientY, ox: r.left, oy: r.top }
  fab.value.setPointerCapture(e.pointerId)
}

function onFabPointerMove(e) {
  if (!drag) return
  const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy
  if (Math.abs(dx) + Math.abs(dy) > 6) {
    dragMoved = true
    const x = Math.min(Math.max(8, drag.ox + dx), window.innerWidth - fab.value.offsetWidth - 8)
    const y = Math.min(Math.max(8, drag.oy + dy), window.innerHeight - fab.value.offsetHeight - 8)
    fabStyle.value = { left: x + 'px', top: y + 'px' }
  }
}

function onFabPointerUp() {
  if (dragMoved) {
    localStorage.setItem(FAB_POS_KEY, JSON.stringify({ x: fab.value.offsetLeft, y: fab.value.offsetTop }))
  }
  drag = null
}

function onFabClick() {
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
    </div>

    <!-- 阅读框 -->
    <div class="rounded-3xl bg-white border border-neutral-100 shadow-card flex flex-col overflow-hidden relative" :style="{ height: shellHeight }">
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
            <button @click="toggleLike"
              class="px-3 py-1.5 rounded-xl border text-xs font-medium transition"
              :class="liked
                ? 'bg-accent-50 border-accent-400 text-accent-600'
                : 'bg-white border-neutral-200 text-neutral-500 hover:border-accent-400 hover:text-accent-600'">
              <i class="fa mr-1.5" :class="liked ? 'fa-heart' : 'fa-heart-o'"></i>点赞 {{ likeCount }}
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

        <div ref="pagesShell" class="flex-1 min-h-0 px-8 lg:px-10 pt-6 pb-14 overflow-hidden bg-[#FBF9F3]">
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
