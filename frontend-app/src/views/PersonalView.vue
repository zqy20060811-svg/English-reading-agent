<script setup>
// 个人中心：用户信息 + 阅读统计 + 最近阅读（点击续读）
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import BookCover from '../components/BookCover.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { api } from '../api/client'
import { LEVEL_NAMES, store, toast } from '../store'

const router = useRouter()
const loading = ref(true)
const stats = ref(null)   // { read_books, liked_count, favorite_count, translation_count, translation_chars, level }
const history = ref([])   // 最近阅读

onMounted(async () => {
  try {
    const [s, h] = await Promise.all([api('/me/stats'), api('/me/history?limit=10')])
    stats.value = s
    history.value = h
  } catch (err) {
    toast('个人中心加载失败：' + err.message)
  } finally {
    loading.value = false
  }
})

const statCards = () => [
  { icon: 'fa-book', label: '读过的书', value: stats.value.read_books },
  { icon: 'fa-heart', label: '点赞', value: stats.value.liked_count },
  { icon: 'fa-star', label: '收藏', value: stats.value.favorite_count },
  { icon: 'fa-language', label: '翻译次数', value: stats.value.translation_count },
]

function openBook(bookId) {
  router.push({ name: 'reader', params: { bookId: String(bookId) } })
}

function fmtTime(iso) {
  try { return new Date(iso).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) } catch { return '' }
}
</script>

<template>
  <div class="p-6 lg:p-10 max-w-4xl mx-auto">
    <!-- 用户信息头 -->
    <div class="flex items-center gap-5">
      <div class="w-16 h-16 rounded-full bg-ink text-white flex items-center justify-center text-2xl font-bold shadow-card select-none">
        {{ (store.username[0] || 'R').toUpperCase() }}
      </div>
      <div>
        <h2 class="text-2xl font-extrabold flex items-center gap-2">
          {{ store.username }}
          <span class="text-xs font-semibold px-2.5 py-1 rounded-full text-accent-600 bg-accent-50 border border-accent-100">
            {{ stats?.level ? stats.level + ' ' + (LEVEL_NAMES[stats.level] || '') : '未测试' }}
          </span>
        </h2>
        <p class="text-sm text-soft mt-1">坚持阅读，让英语 level up</p>
      </div>
      <button @click="router.push({ name: 'settings' })"
        class="ml-auto px-4 py-2 rounded-full bg-white border border-neutral-200 text-xs font-medium text-neutral-600 hover:border-accent-400 hover:text-accent-600 transition">
        <i class="fa fa-cog mr-1.5"></i>设置
      </button>
    </div>

    <!-- 统计卡片 -->
    <div v-if="loading" class="py-16 text-center text-soft">
      <i class="fa fa-circle-o-notch fa-spin text-2xl"></i>
      <p class="mt-3 text-sm">加载中...</p>
    </div>
    <template v-else-if="stats">
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-8">
        <div v-for="c in statCards()" :key="c.label"
          class="rounded-2xl bg-white border border-neutral-100 shadow-card p-4 flex flex-col items-center gap-1">
          <i class="fa text-xl text-accent-500" :class="c.icon"></i>
          <div class="text-2xl font-extrabold leading-tight">{{ c.value }}</div>
          <div class="text-xs text-soft">{{ c.label }}</div>
        </div>
      </div>
      <p class="text-xs text-soft mt-3">
        <i class="fa fa-font mr-1"></i>翻译累计 {{ stats.translation_chars }} 字符 ·
        <i class="fa fa-flag-checkered ml-1 mr-1"></i>在读 / 读过章节 {{ stats.chapters_finished }} 章
      </p>
    </template>

    <!-- 最近阅读 -->
    <h3 class="mt-10 mb-4 font-bold flex items-center gap-2">
      <i class="fa fa-history text-accent-500"></i>最近阅读
    </h3>
    <div v-if="!loading && !history.length" class="py-10 text-center text-soft text-sm">
      还没有阅读记录，<router-link to="/" class="text-accent-600 underline">去书库挑一本书</router-link>吧
    </div>
    <div v-else class="flex flex-col gap-3">
      <div v-for="h in history" :key="h.book_id"
        class="flex items-center gap-4 rounded-2xl bg-white border border-neutral-100 shadow-card p-3 pr-5 cursor-pointer hover:shadow-float hover:-translate-y-0.5 transition"
        @click="openBook(h.book_id)">
        <div class="w-14 h-20 rounded-xl overflow-hidden shadow-card shrink-0">
          <BookCover :book="h" />
        </div>
        <div class="flex-1 min-w-0 py-1">
          <div class="book-title font-bold truncate">{{ h.title }}</div>
          <div class="text-xs text-soft mt-0.5">读到第 {{ h.chapter_index }} 章 · {{ Math.round(h.percent) }}%</div>
          <div class="mt-2 max-w-[240px]">
            <ProgressBar :percent="h.percent" />
          </div>
        </div>
        <div class="text-xs text-soft shrink-0 self-end pb-1">{{ fmtTime(h.updated_at) }}</div>
      </div>
    </div>
  </div>
</template>
