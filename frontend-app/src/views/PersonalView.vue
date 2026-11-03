<script setup lang="ts">
// 个人中心：用户信息 + 阅读统计 + 最近阅读（点击续读）
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import BookCover from '../components/BookCover.vue'
import ProgressBar from '../components/ProgressBar.vue'
import { api } from '../api/client'
import { LEVEL_NAMES, store, toast } from '../store'
import type { HistoryItem } from '../types'

const router = useRouter()

// 阅读统计
interface Stats {
  read_books: number
  liked_count: number
  favorite_count: number
  translation_count: number
  translation_chars: number
  chapters_finished: number
  level: string | null
}

// 当前用户信息
interface MeInfo {
  email: string
  email_verified: boolean
}

const loading = ref(true)
const stats = ref<Stats | null>(null)   // { read_books, liked_count, favorite_count, translation_count, translation_chars, level }
const history = ref<HistoryItem[]>([])   // 最近阅读
const me = ref<MeInfo | null>(null)      // 当前用户信息（含 email_verified）

// 邮箱验证（开发环境验证码打印到后端控制台）
const verifyCode = ref('')
const sending = ref(false)
const verifying = ref(false)
const cooldown = ref(0)

onMounted(async () => {
  try {
    const [s, h, u] = await Promise.all([api<Stats>('/me/stats'), api<HistoryItem[]>('/me/history?limit=10'), api<MeInfo>('/me')])
    stats.value = s
    history.value = h
    me.value = u
  } catch (err) {
    toast('个人中心加载失败：' + (err as Error).message)
  } finally {
    loading.value = false
  }
})

async function sendCode(): Promise<void> {
  sending.value = true
  try {
    await api('/auth/send-verification', { method: 'POST', body: { email: me.value!.email } })
    toast('验证码已发送（开发环境见后端控制台）', 'success')
    cooldown.value = 60
    const timer: ReturnType<typeof setInterval> = setInterval(() => {
      cooldown.value--
      if (cooldown.value <= 0) clearInterval(timer)
    }, 1000)
  } catch (err) {
    toast('发送失败：' + (err as Error).message)
  } finally {
    sending.value = false
  }
}

async function doVerify(): Promise<void> {
  if (verifyCode.value.trim().length !== 6) { toast('请输入 6 位验证码'); return }
  verifying.value = true
  try {
    await api('/auth/verify-email', {
      method: 'POST',
      body: { email: me.value!.email, code: verifyCode.value.trim() },
    })
    me.value!.email_verified = true
    toast('邮箱验证成功', 'success')
  } catch (err) {
    toast('验证失败：' + (err as Error).message)
  } finally {
    verifying.value = false
  }
}

const statCards = (): { icon: string; label: string; value: number }[] => [
  { icon: 'fa-book', label: '读过的书', value: stats.value!.read_books },
  { icon: 'fa-heart', label: '点赞', value: stats.value!.liked_count },
  { icon: 'fa-star', label: '收藏', value: stats.value!.favorite_count },
  { icon: 'fa-language', label: '翻译次数', value: stats.value!.translation_count },
]

function openBook(bookId: number): void {
  router.push({ name: 'reader', params: { bookId: String(bookId) } })
}

function fmtTime(iso: string): string {
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
          <!-- 英语等级徽章：未测试时醒目引导，点击进入水平测试（已测试可重测） -->
          <button @click="router.push({ name: 'test' })"
            :title="stats?.level ? '点击重新测试英语水平' : '点击开始英语水平测试'"
            class="text-xs font-semibold px-2.5 py-1 rounded-full transition"
            :class="stats?.level
              ? 'text-accent-600 bg-accent-50 border border-accent-100 hover:bg-accent-100'
              : 'text-white bg-accent-500 shadow-[0_4px_12px_rgba(255,107,44,.35)] hover:bg-accent-600'">
            <i v-if="!stats?.level" class="fa fa-pencil mr-1"></i>
            {{ stats?.level ? stats.level + ' ' + (LEVEL_NAMES[stats.level] || '') : '未测试 · 去测试' }}
          </button>
        </h2>
        <p class="text-sm text-soft mt-1">坚持阅读，让英语 level up</p>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <!-- 管理后台入口：仅管理员可见（桌面侧边栏与移动端「我的」页均可直达） -->
        <button v-if="store.me?.is_admin" @click="router.push({ name: 'admin' })"
          class="px-4 py-2 rounded-full bg-ink text-white text-xs font-medium hover:bg-ink-700 transition">
          <i class="fa fa-shield mr-1.5"></i>管理后台
        </button>
        <button @click="router.push({ name: 'settings' })"
          class="px-4 py-2 rounded-full bg-white border border-neutral-200 text-xs font-medium text-neutral-600 hover:border-accent-400 hover:text-accent-600 transition">
          <i class="fa fa-cog mr-1.5"></i>设置
        </button>
      </div>
    </div>

    <!-- 邮箱未验证提示条 -->
    <div v-if="me && !me.email_verified"
      class="mt-4 rounded-2xl bg-amber-50 border border-amber-200 p-4 flex flex-wrap items-center gap-3">
      <i class="fa fa-exclamation-triangle text-amber-500"></i>
      <span class="text-xs text-amber-700">邮箱 <b>{{ me.email }}</b> 尚未验证，验证后可保障账号安全</span>
      <input v-model="verifyCode" maxlength="6" placeholder="6 位验证码"
        class="px-3 py-1.5 rounded-lg bg-white border border-amber-200 outline-none text-xs w-28 focus:border-amber-400" />
      <button :disabled="sending || cooldown > 0" @click="sendCode"
        class="px-3 py-1.5 rounded-full text-xs font-semibold border border-amber-300 text-amber-600 hover:bg-amber-100 transition disabled:opacity-50">
        {{ cooldown > 0 ? `重发(${cooldown}s)` : '发送验证码' }}
      </button>
      <button :disabled="verifying" @click="doVerify"
        class="px-3 py-1.5 rounded-full bg-amber-500 text-white text-xs font-semibold hover:bg-amber-600 transition disabled:opacity-50">
        {{ verifying ? '验证中...' : '验证' }}
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
