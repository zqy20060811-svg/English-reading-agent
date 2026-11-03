<script setup lang="ts">
// 点词查义浮层：展示单词释义卡片，支持收录到生词本
import type { LookupPop } from '../../types'

defineProps<{ lookup: LookupPop; showSave?: boolean }>()
defineEmits<{ close: []; save: [] }>()
</script>

<template>
  <div class="fixed z-[60] w-72 rounded-2xl bg-white border border-neutral-200 shadow-float p-4"
    :style="{ left: lookup.x + 'px', top: lookup.y + 'px' }">
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0">
        <div class="book-title text-lg font-bold leading-tight">{{ lookup.word }}</div>
        <div v-if="lookup.data?.phonetic" class="text-xs text-soft mt-0.5">{{ lookup.data.phonetic }}</div>
      </div>
      <button @click="$emit('close')" class="shrink-0 w-7 h-7 rounded-lg hover:bg-neutral-100 text-soft transition">
        <i class="fa fa-close text-xs"></i>
      </button>
    </div>
    <!-- 加载中 -->
    <div v-if="lookup.loading" class="py-4 text-sm text-soft">
      <i class="fa fa-circle-o-notch fa-spin mr-1"></i>查询释义中...
    </div>
    <!-- 查询失败 -->
    <div v-else-if="lookup.error" class="py-3 text-sm text-red-500">
      <i class="fa fa-exclamation-circle mr-1"></i>{{ lookup.error }}
    </div>
    <!-- 释义 -->
    <template v-else-if="lookup.data">
      <ul class="mt-2 space-y-1.5">
        <li v-for="(s, i) in lookup.data.senses" :key="i" class="text-sm text-ink leading-6">
          <span class="text-accent-500 mr-1">·</span>{{ s }}
        </li>
      </ul>
      <div v-if="lookup.data.example_en" class="mt-3 p-2.5 rounded-xl bg-neutral-50 text-xs leading-5">
        <p class="text-ink">{{ lookup.data.example_en }}</p>
        <p v-if="lookup.data.example_cn" class="text-soft mt-1">{{ lookup.data.example_cn }}</p>
      </div>
      <button v-if="showSave" @click="$emit('save')" :disabled="lookup.saved"
        class="mt-3 w-full py-2 rounded-xl text-xs font-semibold transition"
        :class="lookup.saved
          ? 'bg-emerald-50 text-emerald-600 cursor-default'
          : 'bg-accent-500 text-white hover:bg-accent-600'">
        <i class="fa mr-1.5" :class="lookup.saved ? 'fa-check' : 'fa-plus'"></i>
        {{ lookup.saved ? '已在生词本中' : '收录到生词本' }}
      </button>
    </template>
  </div>
</template>
