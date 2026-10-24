<script setup>
// 书库主页：Continue reading 深色大卡 + 分类筛选 + 书格（分页展示）
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import BookCover from '../components/BookCover.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { api, LAST_BOOK_KEY } from '../api/client'
import { genreCn } from '../genres'
import { levelOf, LEVEL_NAMES, loadBooks, store, toast } from '../store'

const router = useRouter()

const loading = ref(true)
const lastBook = ref(null)     // { book_id, chapter_index, percent }
const lastBookData = ref(null) // 书目详情
const genre = ref('全部')
const search = ref('')
const hotIds = ref(new Set()) // 热门榜单前 3 的书籍 id（角标展示）

// 分页（书库书量增长后避免单页过长）
const PAGE_SIZE = 12
const page = ref(1)

watch([genre, search], () => {
  page.value = 1 // 切换筛选/搜索后回到第一页
})

onMounted(async () => {
  try {
    await loadBooks()
    // 热门榜单（失败不影响书库展示）
    try {
      const hot = await api('/books/hot?limit=3')
      hotIds.value = new Set(hot.map(h => h.book_id))
    } catch { /* 榜单加载失败忽略 */ }
    // 最近阅读（localStorage 记录）
    try {
      const last = JSON.parse(localStorage.getItem(LAST_BOOK_KEY) || 'null')
      if (last && store.books.some(b => b.id === last.book_id)) {
        lastBook.value = last
        lastBookData.value = store.books.find(b => b.id === last.book_id)
      }
    } catch { /* 记录损坏则忽略 */ }
  } catch (err) {
    toast('书库加载失败：' + err.message)
  } finally {
    loading.value = false
  }
})

const genres = computed(() => ['全部', ...new Set(store.books.map(b => b.genre).filter(Boolean))])

const filtered = computed(() => {
  const kw = search.value.trim().toLowerCase()
  return store.books.filter(b =>
    (genre.value === '全部' || (b.genre || 'Classic') === genre.value) &&
    (!kw || (b.title || '').toLowerCase().includes(kw) || (b.author || '').toLowerCase().includes(kw)))
})

const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE_SIZE)))
const paged = computed(() => filtered.value.slice((page.value - 1) * PAGE_SIZE, page.value * PAGE_SIZE))

// 页码按钮列表：超过 7 页时收拢为「1 2 … n-1 n」形式
const pageList = computed(() => {
  const total = totalPages.value
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const cur = page.value
  const wanted = new Set([1, 2, cur - 1, cur, cur + 1, total - 1, total])
  const list = [...wanted].filter(p => p >= 1 && p <= total).sort((a, b) => a - b)
  const out = []
  let prev = 0
  for (const p of list) {
    if (p - prev > 1) out.push('…')
    out.push(p)
    prev = p
  }
  return out
})

function goPage(p) {
  if (typeof p !== 'number') return
  page.value = Math.min(Math.max(1, p), totalPages.value)
}

function openBook(bookId) {
  router.push({ name: 'reader', params: { bookId: String(bookId) } })
}

function openContinue() {
  if (!lastBook.value) return
  openBook(lastBook.value.book_id)
}
</script>

<template>
  <div class="p-6 lg:p-10 max-w-7xl mx-auto">
    <!-- ============ Continue reading ============ -->
    <section class="rounded-3xl bg-ink text-white p-6 lg:p-7 shadow-float">
      <div class="flex items-center justify-between mb-5">
        <h2 class="text-xl font-extrabold">继续阅读</h2>
        <span v-if="lastBook" class="text-xs text-neutral-400">
          第 {{ lastBook.chapter_index }} 章 · 已读 {{ Math.round(lastBook.percent) }}%
        </span>
      </div>

      <!-- 有最近阅读：横向书卡 -->
      <div v-if="lastBookData" class="flex gap-6 overflow-x-auto no-scrollbar">
        <div class="flex gap-5 cursor-pointer group shrink-0 w-full max-w-md"
          @click="openContinue()">
          <div class="w-28 h-40 rounded-2xl overflow-hidden shadow-float shrink-0 group-hover:scale-[1.02] transition">
            <BookCover :book="lastBookData" />
          </div>
          <div class="flex flex-col min-w-0 py-1">
            <div class="book-title text-xl font-bold truncate group-hover:text-accent-400 transition">{{ lastBookData.title }}</div>
            <div class="text-sm text-neutral-400 mt-1">{{ lastBookData.author }}</div>
            <div class="mt-auto">
              <ProgressBar :percent="lastBook.percent" class="mb-2" />
              <div class="text-xs text-neutral-400">{{ Math.round(lastBook.percent) }}% · 第 {{ lastBook.chapter_index }} 章</div>
            </div>
          </div>
          <div class="self-center ml-auto shrink-0">
            <button class="w-11 h-11 rounded-full bg-white/10 border border-white/15 flex items-center justify-center hover:bg-accent-500 hover:border-accent-500 transition">
              <i class="fa fa-play text-sm"></i>
            </button>
          </div>
        </div>
      </div>

      <!-- 无记录：引导选书 -->
      <div v-else class="py-4 text-sm text-neutral-400">
        <i class="fa fa-hand-o-right mr-2 text-accent-400"></i>
        从下方书库挑一本书开始今天的阅读吧。
      </div>
    </section>

    <!-- ============ Library ============ -->
    <section class="mt-9">
      <div class="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h2 class="text-2xl font-extrabold">书库</h2>
          <p class="text-sm text-soft mt-1">共 {{ filtered.length }} 本{{ genre === '全部' ? '' : ' · ' + genreCn(genre) }}</p>
        </div>
        <!-- 搜索 -->
        <div class="relative">
          <i class="fa fa-search absolute left-4 top-1/2 -translate-y-1/2 text-soft text-sm"></i>
          <input v-model="search" placeholder="搜索书名或作者..."
            class="w-64 pl-10 pr-4 py-2.5 rounded-2xl bg-white border border-neutral-200 outline-none text-sm focus:border-accent-500 transition" />
        </div>
      </div>

      <!-- 分类 pill -->
      <div class="flex flex-wrap gap-2 mt-4">
        <button v-for="g in genres" :key="g" @click="genre = g"
          class="px-4 py-1.5 rounded-full text-xs font-medium border transition"
          :class="genre === g
            ? 'bg-accent-500 border-accent-500 text-white shadow-[0_6px_16px_rgba(255,107,44,.35)]'
            : 'bg-white border-neutral-200 text-neutral-500 hover:border-accent-400 hover:text-accent-600'">
          {{ g === '全部' ? g : genreCn(g) }}
        </button>
      </div>

      <!-- 书格：封面 + 衬线书名 + 作者 + 进度 -->
      <div v-if="loading" class="py-20 text-center text-soft">
        <i class="fa fa-circle-o-notch fa-spin text-2xl"></i>
        <p class="mt-3 text-sm">书库加载中...</p>
      </div>
      <div v-else-if="!filtered.length" class="py-20 text-center text-soft text-sm">该筛选条件下暂无书籍</div>
      <template v-else>
        <div class="grid sm:grid-cols-2 xl:grid-cols-3 gap-x-8 gap-y-7 mt-6">
          <div v-for="b in paged" :key="b.id"
          class="flex gap-4 cursor-pointer group"
          @click="openBook(b.id)">
          <div class="w-[104px] h-[148px] rounded-2xl overflow-hidden shadow-card shrink-0 group-hover:shadow-float group-hover:scale-[1.02] transition">
            <BookCover :book="b" />
          </div>
          <div class="flex flex-col min-w-0 flex-1 py-1">
            <div class="flex items-start gap-1.5 min-w-0">
              <div class="book-title text-lg font-bold leading-snug line-clamp-2 group-hover:text-accent-600 transition">{{ b.title }}</div>
              <span v-if="hotIds.has(b.id)" title="热门书籍"
                class="shrink-0 mt-0.5 px-1.5 py-0.5 rounded-md bg-accent-500 text-white text-[10px] font-bold leading-none">
                <i class="fa fa-fire mr-0.5"></i>热
              </span>
            </div>
            <div class="text-xs text-soft mt-1 truncate">{{ b.author }}</div>
            <div class="mt-auto">
              <ProgressBar :percent="lastBook && lastBook.book_id === b.id ? lastBook.percent : 0" class="mb-1.5" />
              <div class="flex items-center justify-between text-[11px] text-soft">
                <span>{{ lastBook && lastBook.book_id === b.id ? `${Math.round(lastBook.percent)}% · 第 ${lastBook.chapter_index} 章` : '未开始' }}</span>
                <span class="px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-600 font-medium">
                  {{ levelOf(b.word_count) }} {{ LEVEL_NAMES[levelOf(b.word_count)] || '' }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

        <!-- 分页 -->
        <div v-if="totalPages > 1" class="flex items-center justify-center gap-2 mt-10">
          <button :disabled="page === 1" @click="goPage(page - 1)"
            class="px-4 py-2 rounded-full text-xs font-medium border transition disabled:opacity-40 disabled:cursor-not-allowed"
            :class="page === 1 ? 'bg-white border-neutral-200 text-neutral-400' : 'bg-white border-neutral-200 text-neutral-600 hover:border-accent-400 hover:text-accent-600'">
            <i class="fa fa-angle-left mr-1"></i>上一页
          </button>
          <button v-for="(p, i) in pageList" :key="i" :disabled="p === '…'" @click="goPage(p)"
            class="w-9 h-9 rounded-full text-xs font-medium border transition"
            :class="p === page
              ? 'bg-accent-500 border-accent-500 text-white shadow-[0_6px_16px_rgba(255,107,44,.35)]'
              : p === '…'
                ? 'bg-transparent border-transparent text-neutral-400 cursor-default'
                : 'bg-white border-neutral-200 text-neutral-600 hover:border-accent-400 hover:text-accent-600'">
            {{ p }}
          </button>
          <button :disabled="page === totalPages" @click="goPage(page + 1)"
            class="px-4 py-2 rounded-full text-xs font-medium border transition disabled:opacity-40 disabled:cursor-not-allowed"
            :class="page === totalPages ? 'bg-white border-neutral-200 text-neutral-400' : 'bg-white border-neutral-200 text-neutral-600 hover:border-accent-400 hover:text-accent-600'">
            下一页<i class="fa fa-angle-right ml-1"></i>
          </button>
          <span class="text-xs text-soft ml-2">第 {{ page }} / {{ totalPages }} 页</span>
        </div>
      </template>
    </section>
  </div>
</template>
