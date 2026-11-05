<script setup lang="ts">
// 页面级返回按钮：优先路由历史回退，无历史（直达链接/刷新进入）时回退到指定页（默认书库）
import { useRouter } from 'vue-router'

const props = withDefaults(defineProps<{ fallback?: string }>(), { fallback: '/' })
const router = useRouter()

function goBack(): void {
  // vue-router 4 会在 history.state.back 记录来源路由；没有说明是刷新/直达进入
  if (window.history.state?.back) router.back()
  else router.replace(props.fallback)
}
</script>

<template>
  <button @click="goBack" title="返回"
    class="shrink-0 w-9 h-9 rounded-full border border-neutral-200 bg-white text-neutral-500 hover:text-ink hover:border-neutral-300 flex items-center justify-center transition shadow-sm">
    <i class="fa fa-arrow-left text-sm"></i>
  </button>
</template>
