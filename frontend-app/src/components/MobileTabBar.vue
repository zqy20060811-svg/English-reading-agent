<script setup lang="ts">
// 移动端底部 Tab 导航：书库 / 书架 / 阅读 / 生词本 / 我的（仅 <lg 屏幕显示）
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { store } from '../store'

const route = useRoute()

interface TabItem {
  name: string
  icon: string
  label: string
}

const tabs: TabItem[] = [
  { name: 'library', icon: 'fa-th-large', label: '书库' },
  { name: 'shelf', icon: 'fa-bookmark-o', label: '书架' },
  { name: 'upload', icon: 'fa-cloud-upload', label: '上传' },
  { name: 'reader', icon: 'fa-book', label: '阅读' },
  { name: 'vocabulary', icon: 'fa-graduation-cap', label: '生词本' },
  { name: 'profile', icon: 'fa-user-o', label: '我的' },
]

const activeName = computed(() =>
  route.name === 'library' || route.name === 'rank' ? 'library' : String(route.name || ''))
const avatar = computed(() => (store.username[0] || 'R').toUpperCase())
</script>

<template>
  <!-- 与桌面侧边栏同色系的深色底部导航，安全区适配 iPhone 底部横条 -->
  <nav class="lg:hidden fixed inset-x-0 bottom-0 z-40 bg-ink/95 backdrop-blur border-t border-white/5"
    style="padding-bottom: env(safe-area-inset-bottom)">
    <div class="flex items-stretch justify-around">
      <router-link v-for="tab in tabs" :key="tab.name" :to="{ name: tab.name }"
        class="flex-1 flex flex-col items-center gap-0.5 py-2.5 transition"
        :class="activeName === tab.name ? 'text-accent-400' : 'text-neutral-400'">
        <!-- 我的：用户头像特殊渲染 -->
        <template v-if="tab.name === 'profile'">
          <span class="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold"
            :class="activeName === tab.name ? 'bg-accent-400 text-ink' : 'bg-white/15 text-white'">{{ avatar }}</span>
        </template>
        <i v-else class="fa text-base leading-6" :class="tab.icon"></i>
        <span class="text-[10px]">{{ tab.label }}</span>
      </router-link>
    </div>
  </nav>
</template>
