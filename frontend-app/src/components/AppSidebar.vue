<script setup lang="ts">
// 深色悬浮侧边栏：仅图标导航 + 底部用户头像（对照目标设计稿）
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { store, levelText } from '../store'

const route = useRoute()
const router = useRouter()

interface NavItem {
  name: string
  icon: string
  label: string
}

const navs = computed<NavItem[]>(() => {
  const base: NavItem[] = [
    { name: 'library', icon: 'fa-th-large', label: '书库' },
    { name: 'shelf', icon: 'fa-bookmark-o', label: '书架' },
    { name: 'reader', icon: 'fa-book', label: '阅读' },
    { name: 'vocabulary', icon: 'fa-graduation-cap', label: '生词本' },
    { name: 'test', icon: 'fa-pencil-square-o', label: '水平测试' },
    { name: 'translate', icon: 'fa-font', label: '翻译' },
    { name: 'rank', icon: 'fa-fire', label: '排行榜' },
  ]
  // 管理员追加后台入口
  if (store.me?.is_admin) base.push({ name: 'admin', icon: 'fa-shield', label: '管理后台' })
  return base
})

const activeName = computed(() => (route.name === 'library' || route.name === 'login' ? 'library' : (route.name as string)))
const avatar = computed(() => (store.username[0] || 'R').toUpperCase())
</script>

<template>
  <!-- 桌面端侧边栏（移动端由底部 Tab 导航替代） -->
  <aside class="hidden lg:flex fixed inset-y-3 left-3 z-40 w-[68px] bg-ink rounded-3xl flex-col items-center py-4 shadow-float">
    <!-- Logo -->
    <router-link to="/" title="English Reading"
      class="w-11 h-11 rounded-2xl bg-gradient-to-br from-accent-400 to-accent-600 flex items-center justify-center text-white text-lg shadow-[0_8px_20px_rgba(255,107,44,.45)]">
      <i class="fa fa-book"></i>
    </router-link>

    <!-- 主导航 -->
    <nav class="mt-6 flex flex-col items-center gap-1.5">
      <router-link v-for="nav in navs" :key="nav.name" :to="{ name: nav.name }" :title="nav.label"
        class="group relative w-10 h-10 rounded-2xl flex items-center justify-center text-base transition"
        :class="activeName === nav.name ? 'bg-ink-700 text-accent-400' : 'text-neutral-400 hover:text-white hover:bg-ink-700'">
        <i class="fa" :class="nav.icon"></i>
        <!-- 悬停气泡 -->
        <span class="pointer-events-none absolute left-[50px] whitespace-nowrap rounded-lg bg-ink px-2.5 py-1 text-xs text-white opacity-0 shadow-float transition group-hover:opacity-100">
          {{ nav.label }}
        </span>
      </router-link>
    </nav>

    <div class="flex-1"></div>

    <!-- 设置 + 头像 -->
    <button @click="router.push({ name: 'settings' })" title="设置"
      class="mb-3 w-10 h-10 rounded-2xl flex items-center justify-center text-base transition"
      :class="activeName === 'settings' ? 'bg-ink-700 text-accent-400' : 'text-neutral-400 hover:text-white hover:bg-ink-700'">
      <i class="fa fa-cog"></i>
    </button>
    <button @click="router.push({ name: 'profile' })" :title="`${store.username} · ${levelText()}（个人中心）`"
      class="w-10 h-10 rounded-full bg-white flex items-center justify-center font-bold text-ink cursor-pointer select-none transition hover:ring-2 hover:ring-accent-400"
      :class="activeName === 'profile' ? 'ring-2 ring-accent-400' : ''">
      {{ avatar }}
    </button>
  </aside>
</template>
