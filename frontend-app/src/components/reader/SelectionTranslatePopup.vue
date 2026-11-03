<script setup lang="ts">
// 划句翻译浮层：选区上方的翻译按钮 + 译文结果卡片
import type { SelBubble } from '../../types'

defineProps<{
  bar: SelBubble | null
  result: SelBubble | null
  translating: boolean
}>()
defineEmits<{ translate: []; 'close-result': [] }>()
</script>

<template>
  <!-- 翻译按钮 -->
  <div v-if="bar" class="fixed z-[60] -translate-x-1/2 flex rounded-full bg-ink text-white shadow-float overflow-hidden"
    :style="{ left: bar.x + 'px', top: bar.y + 'px' }">
    <button @click="$emit('translate')" class="px-4 py-2 text-xs font-medium hover:bg-ink-700 transition whitespace-nowrap">
      <i class="fa fa-language mr-1 text-accent-400"></i>翻译这句话
    </button>
  </div>
  <!-- 译文卡片 -->
  <div v-if="result" class="fixed z-[60] -translate-x-1/2 w-80 max-w-[90vw] rounded-2xl bg-white border border-neutral-200 shadow-float p-4"
    :style="{ left: result.x + 'px', top: result.y + 'px' }">
    <div class="flex items-start justify-between gap-2">
      <span class="text-[11px] font-bold text-soft shrink-0"><i class="fa fa-language mr-1 text-accent-500"></i>译文</span>
      <button @click="$emit('close-result')" class="shrink-0 w-7 h-7 rounded-lg hover:bg-neutral-100 text-soft transition">
        <i class="fa fa-close text-xs"></i>
      </button>
    </div>
    <div v-if="translating" class="py-2 text-sm text-soft"><i class="fa fa-circle-o-notch fa-spin mr-1"></i>翻译中...</div>
    <p v-else class="text-sm text-ink leading-7 whitespace-pre-line">{{ result.text }}</p>
  </div>
</template>
