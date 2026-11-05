<script setup lang="ts">
// 书籍封面：优先走后端本地缓存代理 /covers/{id}（外站原图只下载一次 + 浏览器长缓存），
// 无 id 的条目退回原外链；加载失败 / 无封面回退树皮纹理占位
import { computed, ref } from 'vue'
import { API_BASE } from '../api/client'
import type { CoverBook } from '../types'

const props = defineProps<{ book: CoverBook }>()

const broken = ref(false)
// 本地代理地址：有 id 且有 cover_url 才可用（cover_url 仅作为"是否存在封面"的判断依据）
const proxySrc = computed(() => {
  const id = props.book.id ?? props.book.book_id
  return props.book.cover_url && id != null ? `${API_BASE}/covers/${id}` : null
})
// 无 id（如历史兜底条目）退回外链
const externalSrc = computed(() => (proxySrc.value ? null : props.book.cover_url))
</script>

<template>
  <div v-if="(proxySrc || externalSrc) && !broken" class="h-full w-full overflow-hidden bg-neutral-100">
    <img :src="proxySrc ?? externalSrc!" :alt="book.title" loading="lazy" class="h-full w-full object-cover"
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
