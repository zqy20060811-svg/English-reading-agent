<script setup lang="ts">
// 生词本：收藏的生词列表，展示来源书与上下文例句，支持移除
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, apiErrorMessage } from '../api/client'
import { toast } from '../store'
import type { VocabItem } from '../types'
import StateBlock from '../components/StateBlock.vue'

const router = useRouter()

const loading = ref(true)
const error = ref('') // 加载失败信息（非空展示重试）
const words = ref<VocabItem[]>([])
const removing = ref<Set<number>>(new Set())

async function loadWords(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    words.value = await api<VocabItem[]>('/vocabulary')
  } catch (err) {
    error.value = apiErrorMessage(err)
  } finally {
    loading.value = false
  }
}

onMounted(loadWords)

async function removeWord(item: VocabItem) {
  if (removing.value.has(item.id)) return
  removing.value.add(item.id)
  try {
    await api(`/vocabulary/${item.id}`, { method: 'DELETE' })
    words.value = words.value.filter(w => w.id !== item.id)
    toast(`已移除「${item.word}」`, 'ok')
  } catch (err) {
    toast('移除失败：' + apiErrorMessage(err))
  } finally {
    removing.value.delete(item.id)
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}
</script>

<template>
  <div class="p-6 lg:p-10 max-w-5xl mx-auto">
    <div class="flex items-end justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-2xl font-extrabold">生词本</h2>
        <p class="text-sm text-soft mt-1">阅读时点击单词查义后即可收录，共 {{ words.length }} 个生词</p>
      </div>
      <button @click="router.push('/')"
        class="px-4 py-2 rounded-2xl bg-white border border-neutral-200 text-sm text-neutral-600 hover:border-accent-400 hover:text-accent-600 transition">
        <i class="fa fa-plus mr-1"></i>去阅读收录
      </button>
    </div>

    <StateBlock v-if="loading" status="loading" />
    <StateBlock v-else-if="error" status="error" :message="'生词本加载失败：' + error" @retry="loadWords" />

    <StateBlock v-else-if="!words.length" status="empty" icon="fa-language" message="生词本还是空的" hint="阅读时点击生词，释义卡片里可一键收藏" />

    <div v-else class="mt-6 space-y-3">
      <div v-for="w in words" :key="w.id"
        class="flex gap-4 items-start p-4 rounded-2xl bg-white border border-neutral-200 shadow-card">
        <div class="min-w-0 flex-1">
          <div class="flex items-baseline gap-2 flex-wrap">
            <span class="book-title text-lg font-bold">{{ w.word }}</span>
            <span class="text-[11px] text-soft">第 {{ w.chapter_index }} 章 · {{ formatDate(w.created_at) }}</span>
          </div>
          <div class="text-xs text-soft mt-0.5 truncate">来自《{{ w.book_title }}》</div>
          <p v-if="w.context_sentence" class="text-sm text-neutral-600 mt-2 bg-neutral-50 rounded-xl px-3 py-2 leading-relaxed">
            {{ w.context_sentence }}
          </p>
        </div>
        <button :disabled="removing.has(w.id)" @click="removeWord(w)" title="移除生词"
          class="shrink-0 w-9 h-9 rounded-xl text-neutral-300 hover:text-red-500 hover:bg-red-50 transition disabled:opacity-40">
          <i class="fa fa-trash"></i>
        </button>
      </div>
    </div>
  </div>
</template>
