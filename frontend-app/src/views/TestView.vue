<script setup>
// 英语水平测试：入口（含上次结果）→ 答题（24 题）→ 结果分析 + 推荐书目
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import BookCover from '../components/BookCover.vue'
import { api } from '../api/client'
import { DIM_NAMES, LEVEL_NAMES, loadLevel, store, toast } from '../store'

const router = useRouter()

const view = ref('landing') // landing | running | result
const lastResult = ref(null)
const paper = ref(null)
const answers = ref([])
const index = ref(0)
const submitting = ref(false)

onMounted(async () => {
  try {
    lastResult.value = await api('/level-test/result')
  } catch { /* 从未测试过 */ }
})

async function startTest() {
  try {
    paper.value = await api('/level-test/questions')
  } catch (err) {
    toast(err.message)
    return
  }
  answers.value = new Array(paper.value.questions.length).fill(null)
  index.value = 0
  view.value = 'running'
}

const q = computed(() => (paper.value ? paper.value.questions[index.value] : null))
const answeredCount = computed(() => answers.value.filter(a => a !== null).length)

function pick(i) {
  answers.value[index.value] = i
}

function prevQ() {
  if (index.value > 0) index.value--
}

function nextQ() {
  if (answers.value[index.value] === null) { toast('请先选择一个答案'); return }
  if (index.value < paper.value.questions.length - 1) { index.value++; return }
  const missing = answers.value.findIndex(a => a === null)
  if (missing !== -1) {
    toast(`第 ${missing + 1} 题还没作答，已为你跳转过去`)
    index.value = missing
    return
  }
  submitTest()
}

async function submitTest() {
  submitting.value = true
  try {
    const result = await api('/level-test/submit', {
      method: 'POST',
      body: { answers: paper.value.questions.map((qq, i) => ({ question_id: qq.id, choice: answers.value[i] })) },
    })
    lastResult.value = result
    store.level = result.level
    view.value = 'result'
    window.scrollTo({ top: 0, behavior: 'smooth' })
  } catch (err) {
    toast('提交失败：' + err.message)
  } finally {
    submitting.value = false
  }
}

function openBook(bookId) {
  router.push({ name: 'reader', params: { bookId: String(bookId) } })
}

const dimRows = computed(() => {
  const r = lastResult.value
  return r ? [['词汇', r.vocabulary_acc], ['语法', r.grammar_acc], ['阅读理解', r.reading_acc]] : []
})

const detailRows = computed(() =>
  lastResult.value ? Object.entries(lastResult.value.level_detail || {}) : [])
</script>

<template>
  <div class="p-6 lg:p-10 max-w-6xl mx-auto">
    <!-- ============ 入口 ============ -->
    <div v-if="view === 'landing'">
      <section class="rounded-3xl bg-ink text-white p-8 lg:p-10 shadow-float relative overflow-hidden">
        <div class="absolute -right-16 -top-16 w-72 h-72 rounded-full bg-accent-500/20 blur-3xl"></div>
        <div class="relative">
          <div class="text-xs text-neutral-400">英语水平初步评估</div>
          <h1 class="text-3xl font-extrabold mt-2">找到适合你的阅读难度</h1>
          <p class="text-sm text-neutral-400 mt-3 max-w-xl leading-7">
            24 道选择题：词汇 / 语法 / 阅读理解 × A2~C1 四个等级，约 10 分钟。完成后推荐匹配难度的书目。
          </p>
          <button @click="startTest"
            class="mt-7 px-7 py-3 rounded-2xl bg-accent-500 text-white font-semibold hover:bg-accent-600 transition shadow-[0_10px_28px_rgba(255,107,44,.4)]">
            <i class="fa fa-play mr-1.5"></i>{{ lastResult ? '重新测试' : '开始测试' }}
          </button>
        </div>
      </section>

      <!-- 上次结果摘要 -->
      <div v-if="lastResult" class="mt-6 rounded-3xl bg-white border border-neutral-100 shadow-card p-6 flex items-center gap-5">
        <div class="text-4xl font-extrabold text-accent-500">{{ lastResult.level }}</div>
        <div class="text-sm">
          <div class="font-bold">{{ LEVEL_NAMES[lastResult.level] || '' }} · 上次测试结果</div>
          <div class="text-soft mt-1">总分 {{ lastResult.total_score }} / {{ lastResult.max_score }} · 推荐阅读难度 {{ lastResult.recommended_level }}（题量有限，结果供参考）</div>
        </div>
      </div>
    </div>

    <!-- ============ 答题中 ============ -->
    <div v-else-if="view === 'running'">
      <div class="flex items-center justify-between mb-6">
        <div>
          <div class="text-xs text-soft">英语水平初步评估</div>
          <h1 class="text-2xl font-extrabold mt-1">第 {{ index + 1 }} 题</h1>
        </div>
        <div class="text-right">
          <div class="text-xs text-soft">进度</div>
          <div class="font-bold">{{ index + 1 }} / {{ paper.questions.length }}</div>
        </div>
      </div>
      <div class="h-1.5 bg-neutral-200 rounded-full overflow-hidden mb-6">
        <div class="h-full bg-accent-500 rounded-full transition-all" :style="{ width: ((index + 1) / paper.questions.length * 100) + '%' }"></div>
      </div>

      <div class="rounded-3xl bg-white border border-neutral-100 shadow-card p-8">
        <div class="flex items-center gap-2 text-xs mb-4">
          <span class="px-3 py-1 rounded-lg bg-accent-50 text-accent-600 font-semibold">{{ DIM_NAMES[q.dimension] || q.dimension }}</span>
          <span class="px-3 py-1 rounded-lg bg-emerald-50 text-emerald-600 font-semibold">难度 {{ q.level }}</span>
          <span class="text-soft ml-1">选择一个答案</span>
        </div>
        <h2 class="text-lg font-bold leading-relaxed whitespace-pre-line">{{ q.text }}</h2>
        <div class="grid md:grid-cols-2 gap-4 mt-6">
          <div v-for="(opt, i) in q.options" :key="i" @click="pick(i)"
            class="border-2 rounded-2xl p-4 cursor-pointer text-sm transition"
            :class="answers[index] === i ? 'border-accent-500 bg-accent-50' : 'border-neutral-100 hover:border-accent-400'">
            <b class="mr-1">{{ 'ABCD'[i] }}.</b>{{ opt }}
          </div>
        </div>
        <div class="flex items-center justify-between mt-8">
          <button @click="prevQ" :disabled="index === 0"
            class="px-5 py-2.5 rounded-2xl border border-neutral-200 text-soft text-sm hover:bg-neutral-50 transition disabled:opacity-40">
            ← 上一题
          </button>
          <span class="text-xs text-soft">已答 {{ answeredCount }} / {{ paper.questions.length }}</span>
          <button @click="nextQ" :disabled="submitting"
            class="px-5 py-2.5 rounded-2xl bg-accent-500 text-white text-sm font-semibold hover:bg-accent-600 transition disabled:opacity-60">
            <i v-if="submitting" class="fa fa-circle-o-notch fa-spin mr-1"></i>
            {{ index === paper.questions.length - 1 ? '提交测试' : '下一题 →' }}
          </button>
        </div>
      </div>
    </div>

    <!-- ============ 结果 ============ -->
    <div v-else-if="view === 'result' && lastResult">
      <section class="rounded-3xl bg-ink text-white p-8 shadow-float relative overflow-hidden">
        <div class="absolute -right-16 -bottom-20 w-72 h-72 rounded-full bg-accent-500/20 blur-3xl"></div>
        <div class="relative flex flex-wrap items-center justify-between gap-4">
          <div>
            <div class="text-xs text-neutral-400">测试完成 · 英语水平初步评估</div>
            <div class="text-5xl font-extrabold mt-2 text-accent-400">{{ lastResult.level }}
              <span class="text-lg font-semibold text-white/90">{{ LEVEL_NAMES[lastResult.level] || '' }}</span>
            </div>
            <p class="text-sm text-neutral-400 mt-2">总分 {{ lastResult.total_score }} / {{ lastResult.max_score }} · 推荐阅读难度 {{ lastResult.recommended_level }}（题量有限，结果供参考）</p>
          </div>
          <button @click="startTest" class="px-6 py-3 rounded-2xl bg-white text-ink font-semibold hover:shadow-xl transition">再测一次</button>
        </div>
      </section>

      <div class="grid lg:grid-cols-[1fr_320px] gap-6 mt-6">
        <!-- 能力分析 -->
        <div class="rounded-3xl bg-white border border-neutral-100 shadow-card p-6">
          <h4 class="font-bold mb-5">能力分析</h4>
          <div v-for="[name, acc] in dimRows" :key="name" class="mb-4">
            <div class="flex justify-between text-sm mb-1.5">
              <span class="text-soft">{{ name }}</span>
              <span class="font-semibold">{{ Math.round(acc * 100) }}%</span>
            </div>
            <div class="h-1.5 bg-neutral-100 rounded-full overflow-hidden">
              <div class="h-full bg-accent-500 rounded-full transition-all" :style="{ width: Math.round(acc * 100) + '%' }"></div>
            </div>
          </div>
          <div class="mt-4 pt-4 border-t border-neutral-100 space-y-2">
            <div v-for="[lv, text] in detailRows" :key="lv" class="flex justify-between text-sm">
              <span class="text-soft">{{ lv }} {{ LEVEL_NAMES[lv] || '' }}</span>
              <span class="font-semibold">{{ text }}</span>
            </div>
          </div>
          <p class="text-xs text-soft mt-4 leading-6">{{ lastResult.analysis?.overall || '' }}</p>
        </div>

        <!-- 推荐书目 -->
        <div class="rounded-3xl bg-white border border-neutral-100 shadow-card p-6">
          <h4 class="font-bold mb-4">推荐书目（点击开始阅读）</h4>
          <div class="space-y-3">
            <div v-for="b in lastResult.recommendations || []" :key="b.book_id"
              class="flex gap-3 rounded-2xl border border-neutral-100 overflow-hidden hover:border-accent-400 cursor-pointer transition p-2"
              @click="openBook(b.book_id)">
              <div class="w-14 h-20 rounded-xl overflow-hidden shrink-0">
                <BookCover :book="b" />
              </div>
              <div class="min-w-0 py-1">
                <div class="book-title font-bold text-sm truncate">{{ b.title }}</div>
                <div class="text-[11px] text-soft mt-1">{{ b.author }}</div>
                <div class="text-[11px] text-soft mt-0.5">平均章节 {{ Math.round(b.avg_chapter_words) }} 词</div>
              </div>
            </div>
            <p v-if="!(lastResult.recommendations || []).length" class="text-sm text-soft">暂无推荐</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
