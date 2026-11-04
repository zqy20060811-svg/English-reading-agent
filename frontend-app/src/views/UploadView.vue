<script setup lang="ts">
// 我的上传：EPUB/TXT 个人电子书上传 + 管理（列表 / 阅读 / 删除）
// 上传后服务端自动创建全书 AI 分析任务：任务状态徽标 + 轮询 + 全书报告弹窗
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, apiErrorMessage } from '../api/client'
import { toast } from '../store'
import type {
  PersonalAnalysisTask,
  PersonalBook,
  PersonalBookReport,
  PersonalBookUploadOut,
  PersonalChapterAnalysis,
} from '../types'

const router = useRouter()

const MAX_MB = 20 // 与后端 PERSONAL_MAX_UPLOAD_MB 一致
const ALLOWED = ['.epub', '.txt']

const books = ref<PersonalBook[]>([])
const statuses = ref<Record<number, PersonalAnalysisTask | null>>({})
const loading = ref(true)
const uploading = ref(false)
const dragOver = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

// ---- 报告弹窗 ----
const reportBook = ref<PersonalBook | null>(null)
const report = ref<PersonalBookReport | null>(null)
const chapterResults = ref<PersonalChapterAnalysis[]>([])
const reportLoading = ref(false)

let pollTimer: number | null = null

onMounted(async () => {
  await loadList()
  await loadStatuses()
})
onBeforeUnmount(() => {
  if (pollTimer) window.clearTimeout(pollTimer)
})

async function loadList(): Promise<void> {
  try {
    books.value = await api<PersonalBook[]>('/personal/books')
  } catch (err) {
    toast('个人书籍加载失败：' + apiErrorMessage(err))
  } finally {
    loading.value = false
  }
}

async function loadStatuses(): Promise<void> {
  await Promise.all(books.value.map(async (b) => {
    try {
      statuses.value[b.id] = await api<PersonalAnalysisTask>(`/personal/books/${b.id}/analysis/status`)
    } catch {
      statuses.value[b.id] = null // 尚无分析任务（如旧版本上传的书）
    }
  }))
  // 有进行中任务时轮询刷新（上传后任务在后台执行，无需用户手动刷新）
  if (books.value.some((b) => ['pending', 'running'].includes(statuses.value[b.id]?.status ?? ''))) {
    schedulePoll()
  }
}

function schedulePoll(): void {
  if (pollTimer) return
  pollTimer = window.setTimeout(async () => {
    pollTimer = null
    await loadStatuses()
  }, 3000)
}

function statusMeta(t: PersonalAnalysisTask | null): { label: string; cls: string; icon: string } | null {
  if (!t) return null
  switch (t.status) {
    case 'pending':
      return { label: '分析排队中', cls: 'bg-neutral-100 text-neutral-500', icon: 'fa-hourglass-half' }
    case 'running':
      return { label: `分析中 ${t.completed_chapters}/${t.total_chapters}`, cls: 'bg-blue-50 text-blue-600', icon: 'fa-circle-o-notch fa-spin' }
    case 'completed':
      return { label: '已完成分析', cls: 'bg-green-50 text-green-600', icon: 'fa-check-circle' }
    case 'failed':
      return { label: '分析失败', cls: 'bg-red-50 text-red-500', icon: 'fa-exclamation-circle' }
    case 'cancelled':
      return { label: '已取消', cls: 'bg-neutral-100 text-neutral-400', icon: 'fa-ban' }
  }
}

// ---- 报告弹窗 ----

function onBadgeClick(b: PersonalBook): void {
  if (statuses.value[b.id]?.status === 'completed') openReport(b)
}

async function openReport(b: PersonalBook): Promise<void> {
  reportBook.value = b
  report.value = null
  chapterResults.value = []
  reportLoading.value = true
  try {
    report.value = await api<PersonalBookReport>(`/personal/books/${b.id}/analysis/report`)
    const metas = await api<{ chapter_index: number; title: string }[]>(`/personal/books/${b.id}/chapters`)
    const results = await Promise.all(
      metas.map((m) =>
        api<PersonalChapterAnalysis>(`/personal/books/${b.id}/analysis/chapters/${m.chapter_index}`).catch(() => null)
      )
    )
    chapterResults.value = results.filter((r): r is PersonalChapterAnalysis => r !== null)
  } catch (err) {
    toast('报告加载失败：' + apiErrorMessage(err))
  } finally {
    reportLoading.value = false
  }
}

function closeReport(): void {
  reportBook.value = null
}

async function cancelTask(b: PersonalBook): Promise<void> {
  try {
    await api(`/personal/books/${b.id}/analysis/cancel`, { method: 'POST' })
    toast('已请求取消分析任务')
    await loadStatuses()
  } catch (err) {
    toast('取消失败：' + apiErrorMessage(err))
  }
}

async function retryTask(b: PersonalBook): Promise<void> {
  try {
    await api(`/personal/books/${b.id}/analysis`, { method: 'POST' })
    toast('已重新开始分析（已完成章节不会重复分析）', 'ok')
    await loadStatuses()
  } catch (err) {
    toast('重试失败：' + apiErrorMessage(err))
  }
}

// ---- 等级配色 ----

function levelClass(level: string): string {
  switch (level) {
    case 'A1': case 'A2': return 'bg-green-100 text-green-700'
    case 'B1': return 'bg-blue-100 text-blue-700'
    case 'B2': return 'bg-amber-100 text-amber-700'
    default: return 'bg-red-100 text-red-600'
  }
}

const GRAMMAR_LABELS: Record<string, string> = {
  passive_voice: '被动语态',
  relative_clause: '定语从句',
  noun_clause: '名词性从句',
  adverbial_clause: '状语从句',
  conditional_mood: '条件/虚拟',
  nonfinite_verb: '非谓语结构',
  perfect_tense: '完成时态',
  inversion_front: '倒装/强调',
}

function grammarLabel(key: string): string {
  return GRAMMAR_LABELS[key] ?? key
}

function extOk(name: string): boolean {
  const dot = name.toLowerCase()
  return ALLOWED.some(ext => dot.endsWith(ext))
}

function validate(file: File): string | null {
  if (!extOk(file.name)) return '仅支持 EPUB 或 TXT 文件'
  if (file.size <= 0) return '文件内容为空'
  if (file.size > MAX_MB * 1024 * 1024) return `文件超过上限 ${MAX_MB}MB`
  return null
}

async function handleFile(file: File | undefined | null): Promise<void> {
  if (!file || uploading.value) return
  const problem = validate(file)
  if (problem) {
    toast(problem)
    return
  }
  uploading.value = true
  try {
    const form = new FormData()
    form.append('file', file)
    const out = await api<PersonalBookUploadOut>('/personal/books', { method: 'POST', form })
    toast(out.duplicated ? '该书已上传过，已定位到原有记录' : `《${out.title}》上传成功，可以开始阅读了`, 'success')
    await loadList()
  } catch (err) {
    toast('上传失败：' + apiErrorMessage(err))
  } finally {
    uploading.value = false
    if (fileInput.value) fileInput.value.value = '' // 允许重复选择同一文件
  }
}

function onPick(e: Event): void {
  handleFile((e.target as HTMLInputElement).files?.[0])
}

function onDrop(e: DragEvent): void {
  dragOver.value = false
  handleFile(e.dataTransfer?.files?.[0])
}

async function removeBook(b: PersonalBook): Promise<void> {
  if (!confirm(`确定删除《${b.title}》吗？\n章节、阅读进度与原始文件将被一并清理，不可恢复。`)) return
  try {
    await api(`/personal/books/${b.id}`, { method: 'DELETE' })
    books.value = books.value.filter(x => x.id !== b.id)
    toast('已删除', 'ok')
  } catch (err) {
    toast('删除失败：' + apiErrorMessage(err))
  }
}

function openReader(b: PersonalBook): void {
  router.push({ name: 'reader-personal', params: { bookId: String(b.id) } })
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`
}
</script>

<template>
  <div class="p-6 lg:p-8 max-w-4xl mx-auto">
    <!-- 页头 -->
    <div class="mb-6">
      <h1 class="text-2xl font-extrabold">我的上传</h1>
      <p class="text-sm text-soft mt-1.5">
        上传私人 EPUB / TXT 电子书，仅自己可见。上传成功后即可立即阅读。
      </p>
    </div>

    <!-- 上传区：点击选择 + 拖拽 -->
    <label
      class="block rounded-3xl border-2 border-dashed p-8 lg:p-10 text-center cursor-pointer transition select-none"
      :class="dragOver ? 'border-accent-500 bg-accent-50' : 'border-neutral-200 bg-white hover:border-accent-400'"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop">
      <input ref="fileInput" type="file" accept=".epub,.txt" class="hidden" :disabled="uploading" @change="onPick" />
      <template v-if="uploading">
        <i class="fa fa-circle-o-notch fa-spin text-3xl text-accent-500"></i>
        <p class="mt-3 text-sm font-semibold">正在上传并解析章节，请稍候...</p>
        <p class="mt-1 text-xs text-soft">大书解析可能需要十几秒</p>
      </template>
      <template v-else>
        <div class="w-14 h-14 mx-auto rounded-2xl bg-accent-50 flex items-center justify-center">
          <i class="fa fa-cloud-upload text-2xl text-accent-500"></i>
        </div>
        <p class="mt-3 text-sm font-semibold">点击选择文件，或拖拽到此处</p>
        <p class="mt-1.5 text-xs text-soft">支持 EPUB / TXT · 单文件不超过 {{ MAX_MB }}MB</p>
      </template>
    </label>

    <!-- 书籍列表 -->
    <div class="mt-8">
      <h2 class="text-sm font-bold text-soft mb-3">
        <i class="fa fa-folder-open-o mr-1.5"></i>已上传（{{ books.length }}）
      </h2>

      <div v-if="loading" class="py-10 text-center text-sm text-soft">
        <i class="fa fa-circle-o-notch fa-spin mr-2"></i>加载中...
      </div>

      <div v-else-if="!books.length" class="py-10 text-center text-sm text-soft">
        还没有上传过书籍，从上方导入第一本吧
      </div>

      <ul v-else class="space-y-3">
        <li v-for="b in books" :key="b.id"
          class="rounded-2xl bg-white border border-neutral-100 shadow-card p-4 flex items-center gap-4 flex-wrap">
          <!-- 类型图标 -->
          <div class="w-11 h-11 shrink-0 rounded-xl bg-accent-50 flex items-center justify-center"
            :title="b.original_filename">
            <i class="fa text-lg text-accent-500" :class="b.source_type === 'epub' ? 'fa-file-pdf-o' : 'fa-file-text-o'"></i>
          </div>
          <!-- 信息 -->
          <div class="flex-1 min-w-[200px]">
            <div class="font-bold text-sm leading-5">{{ b.title }}</div>
            <div class="text-xs text-soft mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span v-if="b.author">{{ b.author }} ·</span>
              <span>{{ b.language.toUpperCase() }}</span>·
              <span>{{ b.chapter_count }} 章</span>·
              <span>{{ (b.word_count / 10000).toFixed(1) }} 万词</span>·
              <span>{{ formatSize(b.file_size) }}</span>·
              <span>{{ b.created_at.slice(0, 10) }} 上传</span>
            </div>
            <!-- AI 分析状态徽标 -->
            <button v-if="statusMeta(statuses[b.id])" @click="onBadgeClick(b)"
              class="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition"
              :class="statusMeta(statuses[b.id])!.cls"
              :title="statuses[b.id]?.error_message || (statuses[b.id]!.status === 'completed' ? '点击查看全书分析报告' : '')">
              <i class="fa" :class="statusMeta(statuses[b.id])!.icon"></i>
              {{ statusMeta(statuses[b.id])!.label }}
              <span v-if="statuses[b.id]!.status === 'completed'" class="ml-0.5">· 查看报告</span>
            </button>
            <span v-if="statuses[b.id]?.status === 'failed' && statuses[b.id]?.error_message"
              class="block text-xs text-red-400 mt-1 truncate max-w-md" :title="statuses[b.id]!.error_message!">
              {{ statuses[b.id]!.error_message }}
            </span>
          </div>
          <!-- 操作 -->
          <div class="flex items-center gap-2 ml-auto">
            <button v-if="['pending', 'running'].includes(statuses[b.id]?.status ?? '')" @click="cancelTask(b)"
              title="取消分析任务"
              class="px-3 py-2 rounded-xl border border-neutral-200 text-xs text-neutral-500 hover:border-amber-300 hover:text-amber-600 transition">
              <i class="fa fa-hand-paper-o"></i>
            </button>
            <button v-if="['failed', 'cancelled'].includes(statuses[b.id]?.status ?? '')" @click="retryTask(b)"
              title="重新分析（已完成章节不会重复分析）"
              class="px-3 py-2 rounded-xl border border-neutral-200 text-xs text-neutral-500 hover:border-accent-400 hover:text-accent-600 transition">
              <i class="fa fa-refresh"></i>
            </button>
            <button @click="openReader(b)"
              class="px-4 py-2 rounded-xl bg-accent-500 text-white text-xs font-semibold hover:bg-accent-600 transition">
              <i class="fa fa-book mr-1"></i>开始阅读
            </button>
            <button @click="removeBook(b)" title="删除（连同章节/进度/原始文件）"
              class="px-3 py-2 rounded-xl border border-neutral-200 text-xs text-neutral-500 hover:border-red-300 hover:text-red-500 transition">
              <i class="fa fa-trash-o"></i>
            </button>
          </div>
        </li>
      </ul>
    </div>

    <!-- 隐私说明 -->
    <p class="mt-8 text-xs text-soft leading-5">
      <i class="fa fa-lock mr-1"></i>个人书籍与公共书库完全隔离：其他用户无法查看或搜索你上传的书，
      个人书籍也不会进入公共 AI 问答的知识库。
    </p>

    <!-- 全书分析报告弹窗 -->
    <Teleport to="body">
      <div v-if="reportBook" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40"
        @click.self="closeReport">
        <div class="bg-white rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto p-6 shadow-2xl">
          <div class="flex items-start justify-between">
            <div>
              <h2 class="text-lg font-bold">AI 全书分析报告</h2>
              <p class="text-xs text-soft mt-1">《{{ reportBook.title }}》</p>
            </div>
            <button @click="closeReport" class="text-neutral-400 hover:text-neutral-600 transition p-1">
              <i class="fa fa-times"></i>
            </button>
          </div>

          <div v-if="reportLoading" class="py-16 text-center text-soft">
            <i class="fa fa-circle-o-notch fa-spin text-2xl"></i>
            <p class="mt-3 text-sm">报告加载中…</p>
          </div>

          <template v-else-if="report">
            <!-- 总览 -->
            <div class="mt-5 grid grid-cols-3 gap-3">
              <div class="rounded-xl bg-neutral-50 p-4 text-center">
                <div class="inline-block px-3 py-1 rounded-lg text-lg font-bold" :class="levelClass(report.overall_level)">
                  {{ report.overall_level }}
                </div>
                <p class="text-xs text-soft mt-2">整体难度等级</p>
              </div>
              <div class="rounded-xl bg-neutral-50 p-4 text-center">
                <div class="text-lg font-bold text-accent-600">{{ report.difficulty_score }}</div>
                <p class="text-xs text-soft mt-2">难度分数（0–100）</p>
              </div>
              <div class="rounded-xl bg-neutral-50 p-4 text-center">
                <div class="text-lg font-bold text-neutral-700">{{ (report.total_word_count / 10000).toFixed(1) }}万</div>
                <p class="text-xs text-soft mt-2">全书总词数</p>
              </div>
            </div>

            <!-- 词汇分布 -->
            <h3 class="mt-6 text-sm font-bold"><i class="fa fa-language text-accent-500 mr-1.5"></i>词汇等级分布</h3>
            <div class="mt-2 flex gap-1.5">
              <div v-for="lv in ['A1', 'A2', 'B1', 'B2', 'C1', 'C2', 'unknown']" :key="lv"
                class="flex-1 rounded-lg px-2 py-2 text-center" :class="lv === 'unknown' ? 'bg-neutral-50' : levelClass(lv)">
                <div class="text-sm font-bold">{{ lv === 'unknown' ? '未知' : lv }}</div>
                <div class="text-xs mt-0.5 opacity-80">{{ report.vocabulary_level_distribution[lv] ?? 0 }} 词</div>
              </div>
            </div>
            <p class="mt-1.5 text-[11px] text-soft">
              基于本地 CEFR 词典（CEFR-J + Octanove C1/C2）统计；“未知”= 词典未收录（多为专有名词与低频词），不代表更难。
            </p>

            <!-- 章节难度 -->
            <h3 class="mt-6 text-sm font-bold"><i class="fa fa-bar-chart text-accent-500 mr-1.5"></i>章节难度分布</h3>
            <div class="mt-2 flex gap-1.5 flex-wrap">
              <span v-for="(count, lv) in report.chapter_difficulty_distribution" :key="lv"
                class="px-2.5 py-1 rounded-lg text-xs font-semibold" :class="levelClass(lv as string)">
                {{ lv }} × {{ count }} 章
              </span>
            </div>

            <!-- 主要语法特征 -->
            <h3 class="mt-6 text-sm font-bold"><i class="fa fa-cubes text-accent-500 mr-1.5"></i>主要语法特征（本地规则初筛）</h3>
            <div class="mt-2 flex gap-1.5 flex-wrap">
              <span v-for="(v, k) in report.main_grammar_features" :key="k"
                class="px-2.5 py-1 rounded-lg text-xs bg-neutral-50 text-neutral-600">
                {{ grammarLabel(k as string) }} × {{ v.count }}
              </span>
            </div>

            <!-- 阅读建议 -->
            <h3 class="mt-6 text-sm font-bold"><i class="fa fa-lightbulb-o text-accent-500 mr-1.5"></i>阅读建议</h3>
            <ul class="mt-2 space-y-1.5">
              <li v-for="(rec, i) in report.reading_recommendations" :key="i"
                class="text-sm text-neutral-600 leading-6 flex gap-2">
                <i class="fa fa-angle-right text-accent-400 mt-1.5"></i>{{ rec }}
              </li>
            </ul>

            <!-- 章节明细 -->
            <h3 class="mt-6 text-sm font-bold"><i class="fa fa-list text-accent-500 mr-1.5"></i>章节分析明细（{{ chapterResults.length }} 章）</h3>
            <div class="mt-2 space-y-2">
              <details v-for="c in chapterResults" :key="c.chapter_index" class="rounded-xl border border-neutral-100">
                <summary class="px-3 py-2.5 text-xs cursor-pointer select-none flex items-center gap-2">
                  <span class="font-semibold">第 {{ c.chapter_index }} 章</span>
                  <span class="px-1.5 py-0.5 rounded text-[11px] font-bold" :class="levelClass(c.difficulty_level)">{{ c.difficulty_level }}</span>
                  <span class="text-soft">{{ c.difficulty_score }} 分 · {{ c.word_count }} 词 · 均句长 {{ c.average_sentence_length }}</span>
                </summary>
                <div class="px-3 pb-3 pt-0 text-xs leading-6 text-neutral-600 border-t border-neutral-100">
                  <p v-if="c.chapter_summary" class="mt-2"><b>章节摘要：</b>{{ c.chapter_summary }}</p>
                  <p v-if="c.reading_suggestion" class="mt-1.5"><b>阅读建议：</b>{{ c.reading_suggestion }}</p>
                  <div v-if="c.grammar_features.llm_focus?.length" class="mt-2 space-y-1.5">
                    <b>语法难点：</b>
                    <div v-for="(f, i) in c.grammar_features.llm_focus" :key="i" class="rounded-lg bg-neutral-50 p-2">
                      <div class="font-semibold text-neutral-700">{{ f.pattern }}</div>
                      <div class="text-soft mt-0.5">例：{{ f.example }}</div>
                      <div class="mt-0.5">{{ f.explanation }}</div>
                    </div>
                  </div>
                </div>
              </details>
            </div>
          </template>
        </div>
      </div>
    </Teleport>
  </div>
</template>
