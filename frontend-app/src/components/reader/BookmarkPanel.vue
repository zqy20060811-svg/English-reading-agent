<script setup lang="ts">
// 书签列表面板：本页书签可移除，其他页书签可跳转
import type { BookmarkItem } from '../../types'

defineProps<{ bookmarks: BookmarkItem[] }>()
defineEmits<{ close: []; jump: [b: BookmarkItem]; remove: [b: BookmarkItem] }>()
</script>

<template>
  <div class="absolute top-16 right-4 z-30 w-80 max-w-[85%] max-h-[70%] overflow-y-auto rounded-2xl bg-white border border-neutral-200 shadow-float p-3">
    <div class="flex items-center justify-between px-1 pb-2">
      <span class="text-xs font-bold text-ink"><i class="fa fa-bookmark mr-1 text-accent-500"></i>本书书签（{{ bookmarks.length }}）</span>
      <button @click="$emit('close')" class="w-7 h-7 rounded-lg hover:bg-neutral-100 text-soft transition"><i class="fa fa-close text-xs"></i></button>
    </div>
    <div v-if="!bookmarks.length" class="px-1 py-4 text-xs text-soft">还没有书签，点击顶部「书签」按钮收藏当前页</div>
    <div v-for="b in bookmarks" :key="b.id"
      class="group flex items-start gap-2 p-2.5 rounded-xl hover:bg-neutral-50 transition cursor-pointer"
      @click="$emit('jump', b)">
      <i class="fa fa-bookmark text-accent-400 text-xs mt-1 shrink-0"></i>
      <div class="min-w-0 flex-1">
        <div class="text-[11px] text-soft">第 {{ b.chapter_index }} 章 · 第 {{ b.page_index + 1 }} 页</div>
        <div class="text-xs text-ink leading-5 line-clamp-2">{{ b.excerpt || '（无摘要）' }}</div>
      </div>
      <button @click.stop="$emit('remove', b)"
        title="删除书签"
        class="shrink-0 w-7 h-7 rounded-lg text-neutral-300 hover:text-red-500 hover:bg-red-50 transition">
        <i class="fa fa-trash text-xs"></i>
      </button>
    </div>
  </div>
</template>
