<script setup>
// 细进度条：橙色填充（对照目标设计稿的书目进度样式）
defineProps({
  percent: { type: Number, default: 0 },
})
</script>

<template>
  <div class="h-[3px] w-full rounded-full bg-neutral-200 overflow-hidden">
    <div class="h-full rounded-full bg-accent-500 transition-all" :style="{ width: Math.min(100, Math.max(0, percent)) + '%' }"></div>
  </div>
</template>
