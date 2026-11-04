<script setup lang="ts">
// 点词查义浮层：展示单词释义卡片，支持收录到生词本
// 个人书籍模式（prediction 存在时）额外展示：CEFR 等级、章内出现次数、取消收录
import type { LookupPop, PredictedWord } from '../../types'

defineProps<{ lookup: LookupPop; showSave?: boolean; prediction?: PredictedWord | null }>()
defineEmits<{ close: []; save: []; remove: [] }>()
</script>

<template>
  <div class="fixed z-[60] w-72 rounded-2xl bg-white border border-neutral-200 shadow-float p-4"
    :style="{ left: lookup.x + 'px', top: lookup.y + 'px' }">
    <div class="flex items-start justify-between gap-2">
      <div class="min-w-0">
        <div class="book-title text-lg font-bold leading-tight">{{ lookup.word }}</div>
        <div v-if="lookup.data?.phonetic" class="text-xs text-soft mt-0.5">{{ lookup.data.phonetic }}</div>
        <!-- 预测信息：CEFR 等级 + 章内出现次数 -->
        <div v-if="prediction" class="flex items-center gap-1.5 mt-1.5 flex-wrap">
          <span class="px-1.5 py-0.5 rounded text-[11px] font-bold bg-accent-50 text-accent-600">
            CEFR {{ prediction.level === 'unknown' ? '未知' : prediction.level }}
          </span>
          <span class="text-[11px] text-soft">本章出现 {{ prediction.count }} 次</span>
        </div>
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
      <div class="mt-3 flex gap-2">
        <!-- 预测模式（个人书预测生词）：可收录可移除 -->
        <template v-if="prediction">
          <button v-if="!lookup.saved" @click="$emit('save')"
            class="flex-1 py-2 rounded-xl text-xs font-semibold transition bg-accent-500 text-white hover:bg-accent-600">
            <i class="fa fa-plus mr-1.5"></i>收录到生词本
          </button>
          <button v-else @click="$emit('remove')"
            class="flex-1 py-2 rounded-xl text-xs font-semibold transition border border-red-200 text-red-500 hover:bg-red-50">
            <i class="fa fa-trash-o mr-1.5"></i>从生词本移除
          </button>
        </template>
        <!-- 普通模式（公共书 / 任意词点击）：收录或已收录禁用态 -->
        <template v-else>
          <button v-if="showSave && !lookup.saved" @click="$emit('save')"
            class="flex-1 py-2 rounded-xl text-xs font-semibold transition bg-accent-500 text-white hover:bg-accent-600">
            <i class="fa fa-plus mr-1.5"></i>收录到生词本
          </button>
          <button v-else-if="lookup.saved" disabled
            class="flex-1 py-2 rounded-xl text-xs font-semibold bg-emerald-50 text-emerald-600 cursor-default">
            <i class="fa fa-check mr-1.5"></i>已在生词本中
          </button>
        </template>
      </div>
    </template>
  </div>
</template>
