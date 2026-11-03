<script setup lang="ts">
// AI 抽屉：问答（RAG，限定本章）+ 翻译本页，两个 Tab
import { nextTick, ref, watch } from 'vue'
import type { QAItem } from '../../types'

const props = defineProps<{
  open: boolean
  tab: 'qa' | 'tr'
  qaHistory: QAItem[]
  qaSending: boolean
  translating: boolean
  pageTranslation: string
}>()
const emit = defineEmits<{
  close: []
  'update:tab': [tab: 'qa' | 'tr']
  ask: [question: string]
  'translate-page': []
}>()

const qaInput = ref('')
const qaList = ref<HTMLElement | null>(null)

function ask(): void {
  const q = qaInput.value.trim()
  if (!q || props.qaSending) return
  emit('ask', q)
  qaInput.value = ''
}

// 新消息（含错误）到达时滚动到底部
watch(() => props.qaHistory.length, async () => {
  await nextTick()
  if (qaList.value) qaList.value.scrollTop = qaList.value.scrollHeight
})

function scopeLabel(scope: string | undefined): string | null {
  if (scope === 'chapter') return '依据：本章内容'
  if (scope === 'book') return '依据：本章 + 全书检索'
  if (scope === 'none') return '未找到相关依据'
  return null
}
</script>

<template>
  <div class="fixed inset-y-0 right-0 w-[380px] max-w-[92vw] bg-white shadow-float z-50 flex flex-col transition-transform duration-300"
    :class="open ? 'translate-x-0' : 'translate-x-full'">
    <div class="p-5 border-b border-neutral-100 flex items-center justify-between">
      <div class="font-bold text-sm">AI 助手 <span class="text-[11px] text-soft font-normal">基于本章内容（RAG）</span></div>
      <button @click="emit('close')" class="w-8 h-8 rounded-lg hover:bg-neutral-100 text-soft transition">
        <i class="fa fa-close"></i>
      </button>
    </div>

    <div class="flex border-b border-neutral-100 text-sm">
      <button @click="emit('update:tab', 'qa')" class="flex-1 py-3 font-semibold border-b-2 transition"
        :class="tab === 'qa' ? 'text-accent-600 border-accent-500' : 'text-soft border-transparent hover:text-accent-500'">
        AI 问答
      </button>
      <button @click="emit('update:tab', 'tr')" class="flex-1 py-3 font-semibold border-b-2 transition"
        :class="tab === 'tr' ? 'text-accent-600 border-accent-500' : 'text-soft border-transparent hover:text-accent-500'">
        翻译本页
      </button>
    </div>

    <!-- 问答面板 -->
    <div v-show="tab === 'qa'" class="flex-1 min-h-0 flex flex-col">
      <div ref="qaList" class="flex-1 overflow-y-auto p-5 space-y-3">
        <p v-if="!qaHistory.length" class="text-xs text-soft leading-6">
          先选择书和章节，再提问效果最好。<br>例如：「这一章发生了什么？」「主人公为什么离开？」
        </p>
        <template v-for="(m, i) in qaHistory" :key="i">
          <div v-if="m.role === 'me'" class="p-3 rounded-2xl rounded-br-md bg-accent-50 text-sm ml-8">{{ m.text }}</div>
          <div v-else-if="m.role === 'ai'" class="mr-8">
            <div class="p-3 rounded-2xl rounded-bl-md bg-neutral-50 border border-neutral-100 text-sm whitespace-pre-line leading-7">{{ m.text }}</div>
            <div v-if="scopeLabel(m.scope)" class="px-1 pt-1 text-[11px] text-soft">
              <i class="fa fa-search mr-1"></i>{{ scopeLabel(m.scope) }}
            </div>
          </div>
          <div v-else class="p-3 rounded-2xl bg-red-50 text-sm text-red-600 mr-8">{{ m.text }}</div>
        </template>
        <div v-if="qaSending" class="p-3 rounded-2xl bg-neutral-50 text-sm text-soft mr-8 w-fit">
          <i class="fa fa-circle-o-notch fa-spin mr-1"></i>AI 思考中...
        </div>
      </div>
      <div class="p-4 border-t border-neutral-100 flex gap-2">
        <input v-model="qaInput" @keydown.enter="ask" placeholder="就本章内容提问..."
          class="flex-1 px-3.5 py-2.5 rounded-2xl bg-neutral-50 border border-neutral-200 focus:border-accent-500 outline-none text-sm" />
        <button @click="ask" :disabled="qaSending"
          class="px-4 rounded-2xl bg-accent-500 text-white text-sm hover:bg-accent-600 transition disabled:opacity-60">
          <i class="fa fa-send"></i>
        </button>
      </div>
    </div>

    <!-- 翻译面板 -->
    <div v-show="tab === 'tr'" class="flex-1 min-h-0 flex flex-col p-5 overflow-y-auto">
      <button @click="emit('translate-page')" :disabled="translating"
        class="w-full py-2.5 rounded-2xl bg-accent-500 text-white text-sm font-semibold hover:bg-accent-600 transition disabled:opacity-60">
        <i v-if="translating" class="fa fa-circle-o-notch fa-spin mr-1"></i>
        <i v-else class="fa fa-language mr-1"></i>
        {{ translating ? '翻译中，约需十几秒...' : '翻译本页' }}
      </button>
      <div v-if="pageTranslation" class="mt-4 p-4 rounded-2xl bg-accent-50 border border-accent-100 text-sm leading-7 whitespace-pre-line">{{ pageTranslation }}</div>
    </div>
  </div>
</template>
