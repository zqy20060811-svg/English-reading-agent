<script setup>
// 书籍封面：有封面用图，加载失败 / 无封面回退树皮纹理占位
import { ref } from 'vue'

const props = defineProps({
  book: { type: Object, required: true },
})

const broken = ref(false)
</script>

<template>
  <div v-if="book.cover_url && !broken" class="h-full w-full overflow-hidden bg-neutral-100">
    <img :src="book.cover_url" :alt="book.title" loading="lazy" class="h-full w-full object-cover"
      @error="broken = true" />
  </div>
  <div v-else class="cover-fallback h-full w-full flex items-center justify-center p-3">
    <div class="text-center px-1">
      <div class="text-[10px] uppercase tracking-widest opacity-80">{{ book.author || '' }}</div>
      <div class="cover-fallback-title mt-2 font-bold text-sm leading-snug">{{ book.title }}</div>
      <div class="mt-2 mx-auto w-10 h-px bg-current opacity-50"></div>
    </div>
  </div>
</template>
