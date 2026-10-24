<script setup>
// 排行榜：基于 /books/hot 的热度榜单（加权行为 + 14 天半衰期 + 贝叶斯收缩，Redis 缓存 10 分钟）
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import BookCover from '../components/BookCover.vue'
import { api } from '../api/client'
import { toast } from '../store'

const router = useRouter()
const loading = ref(true)
const list = ref([]) // [{ rank, book_id, title, author, cover_url, score }]

onMounted(async () => {
  try {
    list.value = await api('/books/hot?limit=50')
  } catch (err) {
    toast('榜单加载失败：' + err.message)
  } finally {
    loading.value = false
  }
})

function openBook(bookId) {
  router.push({ name: 'reader', params: { bookId: String(bookId) } })
}

// 前三名金银铜徽章，其余为中性序号
function badgeClass(rank) {
  if (rank === 1) return 'bg-amber-400 text-white shadow-[0_6px_16px_rgba(251,191,36,.45)]'
  if (rank === 2) return 'bg-neutral-400 text-white'
  if (rank === 3) return 'bg-amber-700 text-white'
  return 'bg-neutral-100 text-neutral-500'
}
</script>

<template>
  <div class="p-6 lg:p-10 max-w-4xl mx-auto">
    <!-- 页头 -->
    <div class="flex items-end justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-2xl font-extrabold flex items-center gap-2">
          <i class="fa fa-fire text-accent-500"></i>热度排行榜
        </h2>
        <p class="text-sm text-soft mt-1">
          浏览 · 读完章节 · 点赞 · 收藏加权计算，14 天半衰期衰减，每 10 分钟刷新
        </p>
      </div>
      <span class="text-xs text-soft">共 {{ list.length }} 本上榜</span>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="py-20 text-center text-soft">
      <i class="fa fa-circle-o-notch fa-spin text-2xl"></i>
      <p class="mt-3 text-sm">榜单加载中...</p>
    </div>

    <!-- 空榜单 -->
    <div v-else-if="!list.length" class="py-20 text-center text-soft text-sm">
      <i class="fa fa-line-chart text-3xl opacity-30"></i>
      <p class="mt-3">暂无热度数据，先去读几页书吧</p>
    </div>

    <!-- 榜单 -->
    <div v-else class="mt-6 flex flex-col gap-3">
      <div v-for="item in list" :key="item.book_id"
        class="flex items-center gap-4 rounded-2xl bg-white border border-neutral-100 shadow-card p-3 pr-5 cursor-pointer hover:shadow-float hover:-translate-y-0.5 transition"
        @click="openBook(item.book_id)">
        <div class="w-9 h-9 rounded-full flex items-center justify-center font-extrabold text-sm shrink-0"
          :class="badgeClass(item.rank)">
          {{ item.rank }}
        </div>
        <div class="w-14 h-20 rounded-xl overflow-hidden shadow-card shrink-0">
          <BookCover :book="item" />
        </div>
        <div class="flex-1 min-w-0 py-1">
          <div class="book-title font-bold truncate">{{ item.title }}</div>
          <div class="text-xs text-soft mt-0.5 truncate">{{ item.author }}</div>
        </div>
        <div class="text-right shrink-0">
          <div class="text-accent-600 font-extrabold text-lg leading-none">{{ item.score.toFixed(1) }}</div>
          <div class="text-[11px] text-soft mt-1">热度值</div>
        </div>
      </div>
    </div>
  </div>
</template>
