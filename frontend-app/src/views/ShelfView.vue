<script setup lang="ts">
// 我的书架：继续阅读 + 正在读（有进度）+ 收藏/点赞的书，断点续读入口
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import BookCover from '../components/BookCover.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { api, LAST_BOOK_KEY, apiErrorMessage } from '../api/client'
import { loadBooks, store } from '../store'
import type { Book, CoverBook, HistoryItem, LastBook } from '../types'
import StateBlock from '../components/StateBlock.vue'

const router = useRouter()

const loading = ref(true)
const history = ref<HistoryItem[]>([])   // 有阅读进度的书
const shelfBooks = ref<Book[]>([])       // 点赞/收藏/读过的书（并集）
const lastBook = ref<LastBook | null>(null)

const lastBookData = computed<HistoryItem | null>(() => {
  if (!lastBook.value) return null
  return (history.value.find(h => h.book_id === lastBook.value!.book_id)
    || shelfBooks.value.find(b => b.id === lastBook.value!.book_id)
    || null) as HistoryItem | null
})

// 读过但不在历史里的书（如刚点赞还没读出进度）从书库补齐信息
onMounted(async () => {
  try {
    const tasks: Promise<unknown>[] = [
      api<HistoryItem[]>('/me/history?limit=50').then(h => (history.value = h)).catch(() => {}),
      api<Book[]>('/books/mine').then(b => (shelfBooks.value = b)).catch(() => {}),
      loadBooks().catch(() => {}),
    ]
    try {
      const last = JSON.parse(localStorage.getItem(LAST_BOOK_KEY) || 'null') as LastBook | null
      if (last && last.book_id) lastBook.value = last
    } catch { /* 记录损坏则忽略 */ }
    await Promise.all(tasks)
    // 用书库缓存补齐书架中缺失的书籍详情（封面/作者等）
    const known = new Set([...history.value.map(h => h.book_id), ...shelfBooks.value.map(b => b.id)])
    for (const b of store.books) {
      if (known.has(b.id) && !shelfBooks.value.some(s => s.id === b.id)) {
        shelfBooks.value.push(b)
      }
    }
  } catch (err) {
    // 子任务已各自静默降级，仅在外层兜底记录（如 localStorage 异常）
    console.warn('书架加载异常：' + apiErrorMessage(err))
  } finally {
    loading.value = false
  }
})

// 历史里有进度 → 继续读；仅收藏 → 从第 1 章开始
function openBook(bookId: number) {
  router.push({ name: 'reader', params: { bookId: String(bookId) } })
}

// 取书架条目的封面信息：优先真实书目，退回历史记录里的标题/封面
function coverOf(id: number): CoverBook {
  const b = shelfBooks.value.find(x => x.id === id) || store.books.find(x => x.id === id)
  if (b) return { id: b.id, title: b.title, author: b.author, cover_url: b.cover_url }
  const h = history.value.find(x => x.book_id === id)
  return { book_id: id, title: h?.title ?? '', author: h?.author ?? '', cover_url: h?.cover_url ?? null }
}

const hasContent = computed(() => history.value.length > 0 || shelfBooks.value.length > 0)
</script>

<template>
  <div class="p-6 lg:p-10 max-w-7xl mx-auto">
    <!-- ============ 继续阅读 ============ -->
    <section class="rounded-3xl bg-ink text-white p-6 lg:p-7 shadow-float">
      <div class="flex items-center justify-between mb-5">
        <h2 class="text-xl font-extrabold">继续阅读</h2>
        <span v-if="lastBook" class="text-xs text-neutral-400">
          第 {{ lastBook.chapter_index }} 章 · 已读 {{ Math.round(lastBook.percent) }}%
        </span>
      </div>

      <div v-if="lastBookData" class="flex gap-5 cursor-pointer group max-w-md"
        @click="openBook(lastBookData.book_id)">
        <div class="w-28 h-40 rounded-2xl overflow-hidden shadow-float shrink-0 group-hover:scale-[1.02] transition">
          <BookCover :book="coverOf(lastBookData.book_id)" />
        </div>
        <div class="flex flex-col min-w-0 py-1">
          <div class="book-title text-xl font-bold truncate group-hover:text-accent-400 transition">{{ lastBookData.title }}</div>
          <div class="text-sm text-neutral-400 mt-1">{{ lastBookData.author }}</div>
          <div class="mt-auto">
            <ProgressBar :percent="lastBookData.percent" class="mb-2" />
            <div class="text-xs text-neutral-400">{{ Math.round(lastBookData.percent) }}% · 第 {{ lastBookData.chapter_index }} 章</div>
          </div>
        </div>
        <div class="self-center ml-auto shrink-0">
          <button class="w-11 h-11 rounded-full bg-white/10 border border-white/15 flex items-center justify-center hover:bg-accent-500 hover:border-accent-500 transition">
            <i class="fa fa-play text-sm"></i>
          </button>
        </div>
      </div>

      <div v-else class="py-4 text-sm text-neutral-400">
        <i class="fa fa-hand-o-right mr-2 text-accent-400"></i>
        书架还是空的，去<a class="text-accent-400 hover:underline" href="/">书库</a>挑一本书开始阅读吧。
      </div>
    </section>

    <!-- ============ 正在读 ============ -->
    <section class="mt-9">
      <h2 class="text-2xl font-extrabold">正在读</h2>
      <StateBlock v-if="loading" status="loading" message="书架加载中..." />
      <div v-else-if="!history.length" class="py-8 text-sm text-soft">还没有阅读记录</div>
      <div v-else class="grid sm:grid-cols-2 xl:grid-cols-3 gap-x-8 gap-y-7 mt-5">
        <div v-for="h in history" :key="h.book_id" class="flex gap-4 cursor-pointer group" @click="openBook(h.book_id)">
          <div class="w-[104px] h-[148px] rounded-2xl overflow-hidden shadow-card shrink-0 group-hover:shadow-float group-hover:scale-[1.02] transition">
            <BookCover :book="coverOf(h.book_id)" />
          </div>
          <div class="flex flex-col min-w-0 flex-1 py-1">
            <div class="book-title text-lg font-bold leading-snug line-clamp-2 group-hover:text-accent-600 transition">{{ h.title }}</div>
            <div class="text-xs text-soft mt-1 truncate">{{ h.author }}</div>
            <div class="mt-auto">
              <ProgressBar :percent="h.percent" class="mb-1.5" />
              <div class="flex items-center justify-between text-[11px] text-soft">
                <span>{{ Math.round(h.percent) }}% · 第 {{ h.chapter_index }} 章</span>
                <span class="px-2 py-0.5 rounded-md bg-accent-50 text-accent-600 font-medium">继续读</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- ============ 我的收藏 / 点赞 ============ -->
    <section v-if="shelfBooks.length" class="mt-9">
      <h2 class="text-2xl font-extrabold">书单</h2>
      <p class="text-sm text-soft mt-1">读过、点赞或收藏过的书都会出现在这里</p>
      <div class="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-5 mt-5">
        <div v-for="b in shelfBooks" :key="b.id" class="cursor-pointer group" @click="openBook(b.id)">
          <div class="w-full aspect-[104/148] rounded-2xl overflow-hidden shadow-card group-hover:shadow-float group-hover:scale-[1.02] transition">
            <BookCover :book="b" />
          </div>
          <div class="book-title text-sm font-semibold mt-2 line-clamp-1 group-hover:text-accent-600 transition">{{ b.title }}</div>
          <div class="text-[11px] text-soft truncate">{{ b.author }}</div>
        </div>
      </div>
    </section>

    <!-- ============ 空状态 ============ -->
    <div v-if="!loading && !hasContent" class="py-16 text-center text-soft">
      <i class="fa fa-book text-4xl"></i>
      <p class="mt-4 text-sm">书架还是空的，去书库开始第一本书吧</p>
      <button @click="router.push('/')"
        class="mt-6 px-6 py-2.5 rounded-2xl bg-accent-500 text-white text-sm font-medium hover:bg-accent-600 transition">
        去书库
      </button>
    </div>
  </div>
</template>
