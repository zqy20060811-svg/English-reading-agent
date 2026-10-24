<script setup>
// 深色悬浮侧边栏：仅图标导航 + 底部用户头像（对照目标设计稿）
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { store, levelText } from '../store'
import { logout } from '../api/client'

const route = useRoute()
const router = useRouter()

const navs = [
  { name: 'library', icon: 'fa-th-large', label: '书库' },
  { name: 'rank', icon: 'fa-fire', label: '排行榜' },
  { name: 'reader', icon: 'fa-book', label: '阅读' },
  { name: 'test', icon: 'fa-pencil-square-o', label: '水平测试' },
  { name: 'translate', icon: 'fa-language', label: '翻译' },
]

const activeName = computed(() => (route.name === 'library' || route.name === 'login' ? 'library' : route.name))
const avatar = computed(() => (store.username[0] || 'R').toUpperCase())

function onLogout() {
  logout()
  router.replace('/login')
}
</script>

<template>
  <aside class="fixed inset-y-3 left-3 z-40 w-[68px] bg-ink rounded-3xl flex flex-col items-center py-4 shadow-float">
    <!-- Logo -->
    <router-link to="/" title="English Reading"
      class="w-11 h-11 rounded-2xl bg-gradient-to-br from-accent-400 to-accent-600 flex items-center justify-center text-white text-lg shadow-[0_8px_20px_rgba(255,107,44,.45)]">
      <i class="fa fa-book"></i>
    </router-link>

    <!-- 主导航 -->
    <nav class="mt-8 flex flex-col items-center gap-2">
      <router-link v-for="nav in navs" :key="nav.name" :to="{ name: nav.name }" :title="nav.label"
        class="group relative w-11 h-11 rounded-2xl flex items-center justify-center text-lg transition"
        :class="activeName === nav.name ? 'bg-ink-700 text-accent-400' : 'text-neutral-400 hover:text-white hover:bg-ink-700'">
        <i class="fa" :class="nav.icon"></i>
        <!-- 悬停气泡 -->
        <span class="pointer-events-none absolute left-[54px] whitespace-nowrap rounded-lg bg-ink px-2.5 py-1 text-xs text-white opacity-0 shadow-float transition group-hover:opacity-100">
          {{ nav.label }}
        </span>
      </router-link>
    </nav>

    <div class="flex-1"></div>

    <!-- 退出 + 头像 -->
    <button @click="onLogout" title="退出登录"
      class="mb-3 w-11 h-11 rounded-2xl flex items-center justify-center text-neutral-400 hover:text-white hover:bg-ink-700 transition">
      <i class="fa fa-sign-out"></i>
    </button>
    <div :title="`${store.username} · ${levelText()}`"
      class="w-10 h-10 rounded-full bg-white flex items-center justify-center font-bold text-ink cursor-default select-none">
      {{ avatar }}
    </div>
  </aside>
</template>
