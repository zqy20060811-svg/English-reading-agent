<script setup lang="ts">
// 我的上传：EPUB/TXT 个人电子书上传 + 管理（列表 / 阅读 / 删除）
// 上传后服务端同步解析章节，返回即可立即阅读（AI 分析为后续阶段）
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, apiErrorMessage } from '../api/client'
import { toast } from '../store'
import type { PersonalBook, PersonalBookUploadOut } from '../types'

const router = useRouter()

const MAX_MB = 20 // 与后端 PERSONAL_MAX_UPLOAD_MB 一致
const ALLOWED = ['.epub', '.txt']

const books = ref<PersonalBook[]>([])
const loading = ref(true)
const uploading = ref(false)
const dragOver = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

onMounted(loadList)

async function loadList(): Promise<void> {
  try {
    books.value = await api<PersonalBook[]>('/personal/books')
  } catch (err) {
    toast('个人书籍加载失败：' + apiErrorMessage(err))
  } finally {
    loading.value = false
  }
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
          </div>
          <!-- 操作 -->
          <div class="flex items-center gap-2 ml-auto">
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
  </div>
</template>
