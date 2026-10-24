<script setup>
// 翻译页：语言选择 / 交换 / 大模型预留 / 历史（localStorage，最多 50 条）
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
import { toast } from '../store'

const HISTORY_KEY = 'era_translate_history'
const MAX_LEN = 5000

const LANGS = [
  { code: 'auto', name: '自动检测' },
  { code: 'zh', name: '简体中文' },
  { code: 'en', name: 'English' },
  { code: 'ja', name: '日本語' },
  { code: 'ko', name: '한국어' },
  { code: 'fr', name: 'Français' },
  { code: 'de', name: 'Deutsch' },
  { code: 'es', name: 'Español' },
  { code: 'ru', name: 'Русский' },
]
// 传给后端 LLM 的语言表述（auto 除外）
const LANG_PROMPTS = { zh: '中文', en: 'English', ja: '日语', ko: '韩语', fr: '法语', de: '德语', es: '西班牙语', ru: '俄语' }
const langName = code => LANGS.find(l => l.code === code)?.name || code

const srcLang = ref('zh')
const tgtLang = ref('en')
const model = ref('deepseek')
const input = ref('')
const output = ref('')
const outputError = ref('')
const translating = ref(false)
const history = ref([])

onMounted(() => {
  try { history.value = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]') } catch { history.value = [] }
})

function swapLangs() {
  if (srcLang.value === 'auto') { toast('自动检测语言无法换向，请先选择具体语言'); return }
  ;[srcLang.value, tgtLang.value] = [tgtLang.value, srcLang.value]
}

async function pasteText() {
  try {
    const text = await navigator.clipboard.readText()
    if (!text) { toast('剪贴板为空'); return }
    input.value = text.slice(0, MAX_LEN)
  } catch {
    toast('无法读取剪贴板，请手动粘贴（Ctrl+V）')
  }
}

async function doTranslate() {
  const text = input.value.trim()
  if (!text) { toast('请输入要翻译的内容'); return }
  if (text.length > MAX_LEN) { toast(`文本超过 ${MAX_LEN} 字符上限`); return }

  const sourceLang = srcLang.value === 'auto' ? 'auto' : LANG_PROMPTS[srcLang.value]
  const targetLang = LANG_PROMPTS[tgtLang.value]
  const label = `${langName(srcLang.value)} → ${langName(tgtLang.value)}`

  translating.value = true
  output.value = ''
  outputError.value = ''
  try {
    const result = await api('/translate', {
      method: 'POST',
      body: { text, source_lang: sourceLang, target_lang: targetLang, provider: model.value },
    })
    output.value = result.translation
    history.value.unshift({ text, translation: result.translation, label, time: new Date().toLocaleString('zh-CN') })
    history.value = history.value.slice(0, 50)
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value))
  } catch (err) {
    outputError.value = err.message
  } finally {
    translating.value = false
  }
}

function copyResult() {
  if (!output.value) return
  navigator.clipboard.writeText(output.value).then(() => toast('已复制到剪贴板', 'ok'))
}

function useHistory(i) {
  const h = history.value[i]
  if (!h) return
  input.value = h.text
  output.value = h.translation
  outputError.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function deleteHistory(i) {
  history.value.splice(i, 1)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value))
}

function clearHistory() {
  history.value = []
  localStorage.removeItem(HISTORY_KEY)
  toast('已清空翻译历史', 'ok')
}
</script>

<template>
  <div class="p-6 lg:p-10">
    <div class="max-w-3xl mx-auto">
      <!-- 顶部功能标签（同传 / 批改 / 口语 预留） -->
      <div class="flex items-center gap-8 mb-5">
        <button class="relative pb-2 text-lg font-bold border-b-2 border-accent-500">
          翻译
          <span class="absolute left-1/2 -translate-x-1/2 -bottom-[5px] w-1.5 h-1.5 rounded-full bg-accent-500"></span>
        </button>
        <button @click="toast('同传功能即将开放')" class="pb-2 text-lg text-soft hover:text-ink transition">同传</button>
        <button @click="toast('批改功能即将开放')" class="pb-2 text-lg text-soft hover:text-ink transition">批改</button>
        <button @click="toast('口语功能即将开放')" class="pb-2 text-lg text-soft hover:text-ink transition">口语</button>
      </div>

      <!-- 翻译卡 -->
      <div class="rounded-3xl bg-white border border-neutral-100 shadow-card overflow-hidden">
        <!-- 语言选择条 -->
        <div class="flex items-center gap-2 px-5 py-3.5 border-b border-neutral-100 flex-wrap">
          <select v-model="srcLang" class="flex-1 min-w-32 bg-transparent text-base font-medium outline-none cursor-pointer">
            <option v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.name }}</option>
          </select>
          <button @click="swapLangs" title="交换语言"
            class="w-9 h-9 rounded-full hover:bg-accent-50 text-accent-600 transition shrink-0">
            <i class="fa fa-exchange"></i>
          </button>
          <select v-model="tgtLang" class="flex-1 min-w-32 bg-transparent text-base font-medium outline-none cursor-pointer">
            <option v-for="l in LANGS.filter(x => x.code !== 'auto')" :key="l.code" :value="l.code">{{ l.name }}</option>
          </select>
          <!-- 大模型选择（付费通道预留） -->
          <div class="hidden md:flex items-center gap-1.5 pl-3 border-l border-neutral-100 shrink-0">
            <span class="w-5 h-5 rounded-full bg-gradient-to-br from-accent-400 to-accent-600 flex items-center justify-center text-white text-[10px]">
              <i class="fa fa-magic"></i>
            </span>
            <select v-model="model" class="bg-transparent text-sm text-soft outline-none cursor-pointer">
              <option value="deepseek">AI 大模型</option>
              <option value="gpt" disabled>GPT-4o（即将开放）</option>
              <option value="ernie" disabled>文心一言（即将开放）</option>
              <option value="qwen" disabled>通义千问（即将开放）</option>
            </select>
          </div>
        </div>

        <!-- 输入区 -->
        <div class="px-6 pt-5 pb-4">
          <textarea v-model="input" rows="6" :maxlength="MAX_LEN" placeholder="请输入或粘贴需要翻译的内容"
            class="w-full bg-transparent outline-none resize-none text-lg leading-8 placeholder:text-neutral-300"></textarea>

          <!-- 译文区 -->
          <div v-if="translating" class="border-t border-neutral-100 pt-4 mt-2 text-soft text-sm">
            <i class="fa fa-circle-o-notch fa-spin mr-1"></i>AI 大模型翻译中，约需十几秒...
          </div>
          <div v-else-if="outputError" class="border-t border-neutral-100 pt-4 mt-2 text-red-500 text-sm">翻译失败：{{ outputError }}</div>
          <div v-else-if="output" class="border-t border-neutral-100 pt-4 mt-2 text-lg leading-8 whitespace-pre-line">{{ output }}</div>

          <div class="flex items-center gap-2 mt-4">
            <span class="text-xs text-soft">{{ input.length }} / {{ MAX_LEN }}</span>
            <button @click="pasteText" class="px-3 py-1 rounded-full bg-accent-50 text-accent-600 text-xs hover:bg-accent-100 transition">粘贴</button>
            <button v-if="output" @click="copyResult" class="px-3 py-1 rounded-full bg-emerald-50 text-emerald-600 text-xs hover:bg-emerald-100 transition">
              <i class="fa fa-clipboard mr-1"></i>复制
            </button>
            <div class="ml-auto flex items-center gap-2.5">
              <button @click="toast('录音功能即将开放')"
                class="px-5 py-2 rounded-full bg-accent-50 text-accent-600 text-sm font-medium hover:bg-accent-100 transition">
                <i class="fa fa-microphone mr-1"></i>录音
              </button>
              <button @click="doTranslate" :disabled="translating"
                class="px-7 py-2 rounded-full bg-accent-500 text-white text-sm font-semibold hover:bg-accent-600 transition disabled:opacity-60 shadow-[0_8px_20px_rgba(255,107,44,.35)]">
                翻 译
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 翻译历史 -->
      <div class="mt-8">
        <div class="flex items-center justify-between mb-2">
          <h3 class="text-sm text-soft">翻译历史</h3>
          <button v-if="history.length" @click="clearHistory" class="text-xs text-soft hover:text-red-500 transition">清空全部</button>
        </div>
        <p v-if="!history.length" class="text-sm text-soft py-4">暂无翻译记录</p>
        <div v-else>
          <div v-for="(h, i) in history" :key="i"
            class="group flex items-start gap-3 py-4 border-b border-neutral-100 cursor-pointer hover:bg-accent-50/40 rounded-xl px-3 -mx-3 transition"
            @click="useHistory(i)">
            <div class="flex-1 min-w-0">
              <p class="text-base font-semibold truncate">{{ h.text }}</p>
              <p class="text-soft mt-0.5 truncate text-sm">{{ h.translation }}</p>
              <span class="text-[11px] text-neutral-300 mt-1 inline-block">{{ h.label }} · {{ h.time }}</span>
            </div>
            <button @click.stop="deleteHistory(i)" title="删除"
              class="w-7 h-7 rounded-full text-neutral-300 hover:text-red-500 hover:bg-red-50 transition shrink-0 opacity-60 group-hover:opacity-100">
              <i class="fa fa-times"></i>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
