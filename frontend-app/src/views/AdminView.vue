<script setup lang="ts">
// 管理后台：概览 / 书籍上下架 / 入库任务（含失败重试）/ 用户管理 / AI 用量统计
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, apiErrorMessage } from '../api/client'
import { store, toast } from '../store'
import { genreCn } from '../genres'
import type { AdminBook, AdminOverview, AdminUser, AIStats, IngestTask } from '../types'
import StateBlock from '../components/StateBlock.vue'

type Tab = 'overview' | 'books' | 'tasks' | 'users' | 'ai'
const tab = ref<Tab>('overview')

const loading = ref(true)
const error = ref('')
const overview = ref<AdminOverview | null>(null)

// ================= 通用加载 =================

async function loadOverview(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    overview.value = await api<AdminOverview>('/admin/overview')
  } catch (err) {
    error.value = apiErrorMessage(err)
  } finally {
    loading.value = false
  }
}

function switchTab(t: Tab): void {
  tab.value = t
  if (t === 'overview' && !overview.value) loadOverview()
  if (t === 'books' && !books.value.length) loadBooks()
  if (t === 'tasks' && !tasksLoaded) loadTasks()
  if (t === 'users' && !users.value.length) loadUsers()
  if (t === 'ai' && !stats.value) loadStats()
}

// ================= 书籍上下架 =================

const books = ref<AdminBook[]>([])
const bookQuery = ref('')
const booksLoading = ref(false)
const booksError = ref('')
const togglingBook = ref<Set<number>>(new Set())

async function loadBooks(): Promise<void> {
  booksLoading.value = true
  booksError.value = ''
  try {
    books.value = await api<AdminBook[]>(`/admin/books?query=${encodeURIComponent(bookQuery.value)}`)
  } catch (err) {
    booksError.value = apiErrorMessage(err)
  } finally {
    booksLoading.value = false
  }
}

async function toggleBook(b: AdminBook): Promise<void> {
  togglingBook.value.add(b.id)
  try {
    const updated = await api<AdminBook>(`/admin/books/${b.id}`, {
      method: 'PATCH',
      body: { is_active: !b.is_active },
    })
    b.is_active = updated.is_active
    toast(updated.is_active ? `「${b.title}」已上架` : `「${b.title}」已下架`, 'ok')
  } catch (err) {
    toast('操作失败：' + apiErrorMessage(err))
  } finally {
    togglingBook.value.delete(b.id)
  }
}

// ================= 入库任务 =================

const tasks = ref<IngestTask[]>([])
const tasksLoaded = ref(false)
const tasksLoading = ref(false)
const tasksError = ref('')
const newBookId = ref<number | null>(null)
const newEmbed = ref(false)
const creating = ref(false)
let pollTimer: ReturnType<typeof setInterval> | undefined

const hasActiveTask = computed(() => tasks.value.some(t => t.status === 'pending' || t.status === 'running'))

async function loadTasks(silent = false): Promise<void> {
  if (!silent) tasksLoading.value = true
  tasksError.value = ''
  try {
    tasks.value = await api<IngestTask[]>('/admin/ingest/tasks')
    tasksLoaded.value = true
  } catch (err) {
    tasksError.value = apiErrorMessage(err)
  } finally {
    tasksLoading.value = false
  }
}

async function createTask(): Promise<void> {
  const id = Number(newBookId.value)
  if (!id || id <= 0) { toast('请输入有效的古登堡书号'); return }
  creating.value = true
  try {
    await api('/admin/ingest/tasks', { method: 'POST', body: { gutenberg_id: id, embed: newEmbed.value } })
    toast(`已创建入库任务（书号 ${id}${newEmbed.value ? '，含向量化' : ''}）`, 'ok')
    newBookId.value = null
    await loadTasks(true)
    startPolling()
  } catch (err) {
    toast('创建失败：' + apiErrorMessage(err))
  } finally {
    creating.value = false
  }
}

async function retryTask(t: IngestTask): Promise<void> {
  try {
    await api(`/admin/ingest/tasks/${t.id}/retry`, { method: 'POST' })
    toast(`任务 #${t.id} 已重新调度`, 'ok')
    await loadTasks(true)
    startPolling()
  } catch (err) {
    toast('重试失败：' + apiErrorMessage(err))
  }
}

// 有进行中的任务时每 5 秒轮询刷新状态
function startPolling(): void {
  stopPolling()
  pollTimer = setInterval(() => {
    if (hasActiveTask.value) loadTasks(true)
    else stopPolling()
  }, 5000)
}

function stopPolling(): void {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = undefined }
}

onMounted(() => { if (hasActiveTask.value) startPolling() })
onBeforeUnmount(stopPolling)

const STATUS_META: Record<IngestTask['status'], { label: string; cls: string }> = {
  pending: { label: '待执行', cls: 'bg-neutral-100 text-neutral-500' },
  running: { label: '执行中', cls: 'bg-blue-50 text-blue-600' },
  success: { label: '成功', cls: 'bg-emerald-50 text-emerald-600' },
  failed: { label: '失败', cls: 'bg-red-50 text-red-600' },
}

// ================= 用户管理 =================

const users = ref<AdminUser[]>([])
const usersLoading = ref(false)
const usersError = ref('')
const userQuery = ref('')
const updatingUser = ref<Set<number>>(new Set())

async function loadUsers(): Promise<void> {
  usersLoading.value = true
  usersError.value = ''
  try {
    users.value = await api<AdminUser[]>(`/admin/users?query=${encodeURIComponent(userQuery.value)}`)
  } catch (err) {
    usersError.value = apiErrorMessage(err)
  } finally {
    usersLoading.value = false
  }
}

async function patchUser(u: AdminUser, body: { is_admin?: boolean; is_disabled?: boolean }): Promise<void> {
  updatingUser.value.add(u.id)
  try {
    const updated = await api<AdminUser>(`/admin/users/${u.id}`, { method: 'PATCH', body })
    Object.assign(u, updated)
    if (u.id === store.me?.id) store.me.is_admin = updated.is_admin
    toast(`用户「${u.username}」已更新`, 'ok')
  } catch (err) {
    toast('操作失败：' + apiErrorMessage(err))
  } finally {
    updatingUser.value.delete(u.id)
  }
}

function fmtDate(s: string | null): string {
  return s ? new Date(s).toLocaleDateString('zh-CN') : '—'
}

// ================= AI 用量统计 =================

const stats = ref<AIStats | null>(null)
const statsLoading = ref(false)
const statsError = ref('')
const statsDays = ref(30)

async function loadStats(): Promise<void> {
  statsLoading.value = true
  statsError.value = ''
  try {
    stats.value = await api<AIStats>(`/admin/stats/ai?days=${statsDays.value}`)
  } catch (err) {
    statsError.value = apiErrorMessage(err)
  } finally {
    statsLoading.value = false
  }
}

function fmtNum(n: number): string {
  return n >= 1000 ? n.toLocaleString('en-US') : String(n)
}

onMounted(loadOverview)
</script>

<template>
  <div class="p-6 lg:p-8 max-w-7xl mx-auto">
    <div class="flex items-center justify-between mb-5">
      <h1 class="text-2xl font-extrabold"><i class="fa fa-shield mr-2 text-accent-500"></i>管理后台</h1>
      <span class="text-xs text-soft">{{ store.me?.username }} · 管理员</span>
    </div>

    <!-- Tab 导航 -->
    <div class="flex gap-1.5 mb-6 overflow-x-auto no-scrollbar">
      <button v-for="t in [
        ['overview', '概览', 'fa-dashboard'], ['books', '书籍管理', 'fa-book'],
        ['tasks', '入库任务', 'fa-cloud-download'], ['users', '用户管理', 'fa-users'],
        ['ai', 'AI 统计', 'fa-line-chart'],
      ] as [Tab, string, string][]" :key="t[0]" @click="switchTab(t[0])"
        class="shrink-0 px-4 py-2.5 rounded-2xl text-sm font-semibold transition"
        :class="tab === t[0] ? 'bg-ink text-white' : 'bg-white border border-neutral-200 text-neutral-500 hover:border-accent-400 hover:text-accent-600'">
        <i class="fa mr-1.5" :class="t[2]"></i>{{ t[1] }}
      </button>
    </div>

    <!-- ============ 概览 ============ -->
    <template v-if="tab === 'overview'">
      <StateBlock v-if="loading" status="loading" />
      <StateBlock v-else-if="error" status="error" :message="'概览加载失败：' + error" @retry="loadOverview" />
      <div v-else-if="overview" class="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <div v-for="card in [
          ['fa-users', '注册用户', fmtNum(overview.total_users)],
          ['fa-book', '全部书籍', fmtNum(overview.total_books)],
          ['fa-check-circle', '上架书籍', fmtNum(overview.active_books)],
          ['fa-cloud-download', '进行中任务', fmtNum(overview.running_or_pending_tasks)],
          ['fa-commenting', '今日 AI 调用', fmtNum(overview.ai_calls_today)],
        ]" :key="card[1]" class="rounded-3xl bg-white border border-neutral-100 shadow-card p-5">
          <i class="fa text-xl text-accent-400" :class="card[0]"></i>
          <div class="text-2xl font-extrabold mt-2">{{ card[2] }}</div>
          <div class="text-xs text-soft mt-0.5">{{ card[1] }}</div>
        </div>
      </div>
    </template>

    <!-- ============ 书籍上下架 ============ -->
    <template v-else-if="tab === 'books'">
      <div class="flex gap-2 mb-4">
        <input v-model="bookQuery" @keydown.enter="loadBooks" placeholder="按书名 / 作者搜索..."
          class="flex-1 max-w-xs px-4 py-2.5 rounded-2xl bg-white border border-neutral-200 focus:border-accent-500 outline-none text-sm" />
        <button @click="loadBooks" class="px-5 py-2.5 rounded-2xl bg-accent-500 text-white text-sm font-semibold hover:bg-accent-600 transition">
          <i class="fa fa-search mr-1"></i>搜索
        </button>
      </div>
      <StateBlock v-if="booksLoading" status="loading" />
      <StateBlock v-else-if="booksError" status="error" :message="'书籍列表加载失败：' + booksError" @retry="loadBooks" />
      <StateBlock v-else-if="!books.length" status="empty" icon="fa-book" message="没有匹配的书籍" />
      <div v-else class="rounded-3xl bg-white border border-neutral-100 shadow-card overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-soft border-b border-neutral-100">
              <th class="px-5 py-3 font-semibold">书籍</th>
              <th class="px-3 py-3 font-semibold hidden md:table-cell">分类</th>
              <th class="px-3 py-3 font-semibold hidden lg:table-cell">词数</th>
              <th class="px-3 py-3 font-semibold">书号</th>
              <th class="px-3 py-3 font-semibold text-right">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in books" :key="b.id" class="border-b border-neutral-50 last:border-0 hover:bg-neutral-50/60">
              <td class="px-5 py-3">
                <div class="font-semibold">{{ b.title }}</div>
                <div class="text-xs text-soft">{{ b.author }} · {{ b.year }}</div>
              </td>
              <td class="px-3 py-3 text-xs text-soft hidden md:table-cell">{{ genreCn(b.genre) || b.genre }}</td>
              <td class="px-3 py-3 text-xs text-soft hidden lg:table-cell">{{ b.word_count ? b.word_count.toLocaleString() : '—' }}</td>
              <td class="px-3 py-3 text-xs text-soft">#{{ b.gutenberg_id }}</td>
              <td class="px-3 py-3 text-right">
                <button @click="toggleBook(b)" :disabled="togglingBook.has(b.id)"
                  class="px-3.5 py-1.5 rounded-xl text-xs font-semibold transition disabled:opacity-50"
                  :class="b.is_active
                    ? 'bg-emerald-50 text-emerald-600 hover:bg-red-50 hover:text-red-600'
                    : 'bg-neutral-100 text-neutral-400 hover:bg-emerald-50 hover:text-emerald-600'">
                  <i v-if="togglingBook.has(b.id)" class="fa fa-circle-o-notch fa-spin"></i>
                  <i v-else class="fa mr-1" :class="b.is_active ? 'fa-arrow-down' : 'fa-arrow-up'"></i>
                  {{ b.is_active ? '下架' : '上架' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- ============ 入库任务 ============ -->
    <template v-else-if="tab === 'tasks'">
      <!-- 新建任务 -->
      <div class="rounded-3xl bg-white border border-neutral-100 shadow-card p-5 mb-4">
        <div class="text-sm font-bold mb-3"><i class="fa fa-plus-circle mr-1.5 text-accent-500"></i>新建入库任务</div>
        <div class="flex flex-wrap items-center gap-2">
          <input v-model.number="newBookId" type="number" min="1" placeholder="古登堡书号，如 1342"
            class="w-44 px-4 py-2.5 rounded-2xl bg-neutral-50 border border-neutral-200 focus:border-accent-500 outline-none text-sm" />
          <label class="flex items-center gap-2 text-xs text-soft cursor-pointer select-none">
            <input v-model="newEmbed" type="checkbox" class="accent-orange-500 w-4 h-4" />
            同时向量化（用于 AI 问答，CPU 较慢）
          </label>
          <button @click="createTask" :disabled="creating"
            class="ml-auto px-5 py-2.5 rounded-2xl bg-accent-500 text-white text-sm font-semibold hover:bg-accent-600 transition disabled:opacity-50">
            <i v-if="creating" class="fa fa-circle-o-notch fa-spin mr-1"></i>
            <i v-else class="fa fa-cloud-upload mr-1"></i>创建任务
          </button>
        </div>
        <p class="text-[11px] text-soft mt-2">书号须已在 books_catalog.py 登记元数据；爬取 → 入库 → 切章 → 分块 →（可选）向量化，后台异步执行。</p>
      </div>

      <StateBlock v-if="tasksLoading && !tasksLoaded" status="loading" />
      <StateBlock v-else-if="tasksError && !tasksLoaded" status="error" :message="'任务列表加载失败：' + tasksError" @retry="loadTasks()" />
      <StateBlock v-else-if="tasksLoaded && !tasks.length" status="empty" icon="fa-cloud-download" message="还没有入库任务" hint="在上方输入书号创建第一个任务" />
      <div v-else class="rounded-3xl bg-white border border-neutral-100 shadow-card overflow-hidden">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-soft border-b border-neutral-100">
              <th class="px-5 py-3 font-semibold">任务</th>
              <th class="px-3 py-3 font-semibold">书号</th>
              <th class="px-3 py-3 font-semibold hidden md:table-cell">向量化</th>
              <th class="px-3 py-3 font-semibold hidden lg:table-cell">尝试 / 创建</th>
              <th class="px-3 py-3 font-semibold text-right">状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in tasks" :key="t.id" class="border-b border-neutral-50 last:border-0 align-top">
              <td class="px-5 py-3">
                <span class="font-semibold">#{{ t.id }}</span>
                <div v-if="t.error" class="text-xs text-red-500 mt-1 max-w-md whitespace-pre-line line-clamp-3" :title="t.error">{{ t.error.split('\n')[0] }}</div>
              </td>
              <td class="px-3 py-3 text-xs text-soft">#{{ t.gutenberg_id }}</td>
              <td class="px-3 py-3 text-xs hidden md:table-cell">
                <i class="fa mr-1" :class="t.embed ? 'fa-check text-emerald-500' : 'fa-times text-neutral-300'"></i>
                <span class="text-soft">{{ t.embed ? '是' : '否' }}</span>
              </td>
              <td class="px-3 py-3 text-xs text-soft hidden lg:table-cell">
                {{ t.attempts }} 次<br>{{ fmtDate(t.created_at) }}
              </td>
              <td class="px-3 py-3 text-right">
                <span class="inline-block px-2.5 py-1 rounded-lg text-xs font-semibold" :class="STATUS_META[t.status].cls">
                  <i v-if="t.status === 'running'" class="fa fa-circle-o-notch fa-spin mr-1"></i>
                  {{ STATUS_META[t.status].label }}
                </span>
                <button v-if="t.status === 'failed'" @click="retryTask(t)"
                  class="ml-2 px-3 py-1.5 rounded-xl text-xs font-semibold bg-accent-50 text-accent-600 hover:bg-accent-100 transition">
                  <i class="fa fa-refresh mr-1"></i>重试
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- ============ 用户管理 ============ -->
    <template v-else-if="tab === 'users'">
      <div class="flex gap-2 mb-4">
        <input v-model="userQuery" @keydown.enter="loadUsers" placeholder="按用户名 / 邮箱搜索..."
          class="flex-1 max-w-xs px-4 py-2.5 rounded-2xl bg-white border border-neutral-200 focus:border-accent-500 outline-none text-sm" />
        <button @click="loadUsers" class="px-5 py-2.5 rounded-2xl bg-accent-500 text-white text-sm font-semibold hover:bg-accent-600 transition">
          <i class="fa fa-search mr-1"></i>搜索
        </button>
      </div>
      <StateBlock v-if="usersLoading" status="loading" />
      <StateBlock v-else-if="usersError" status="error" :message="'用户列表加载失败：' + usersError" @retry="loadUsers" />
      <StateBlock v-else-if="!users.length" status="empty" icon="fa-users" message="没有匹配的用户" />
      <div v-else class="rounded-3xl bg-white border border-neutral-100 shadow-card overflow-x-auto">
        <table class="w-full text-sm min-w-[640px]">
          <thead>
            <tr class="text-left text-xs text-soft border-b border-neutral-100">
              <th class="px-5 py-3 font-semibold">用户</th>
              <th class="px-3 py-3 font-semibold hidden md:table-cell">邮箱</th>
              <th class="px-3 py-3 font-semibold hidden lg:table-cell">注册</th>
              <th class="px-3 py-3 font-semibold text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="u in users" :key="u.id" class="border-b border-neutral-50 last:border-0 hover:bg-neutral-50/60">
              <td class="px-5 py-3">
                <div class="font-semibold flex items-center gap-1.5">
                  {{ u.username }}
                  <span v-if="u.is_admin" class="px-1.5 py-0.5 rounded-md bg-accent-50 text-accent-600 text-[10px] font-bold">管理员</span>
                  <span v-if="u.is_disabled" class="px-1.5 py-0.5 rounded-md bg-red-50 text-red-600 text-[10px] font-bold">已禁用</span>
                </div>
                <div class="text-xs text-soft">#{{ u.id }}{{ u.email_verified ? ' · 邮箱已验证' : '' }}</div>
              </td>
              <td class="px-3 py-3 text-xs text-soft hidden md:table-cell">{{ u.email }}</td>
              <td class="px-3 py-3 text-xs text-soft hidden lg:table-cell">{{ fmtDate(u.created_at) }}</td>
              <td class="px-3 py-3 text-right whitespace-nowrap">
                <button @click="patchUser(u, { is_admin: !u.is_admin })" :disabled="updatingUser.has(u.id)"
                  class="px-3 py-1.5 rounded-xl text-xs font-semibold transition disabled:opacity-50"
                  :class="u.is_admin ? 'bg-neutral-100 text-neutral-400 hover:text-red-600' : 'bg-accent-50 text-accent-600 hover:bg-accent-100'">
                  {{ u.is_admin ? '取消管理员' : '设为管理员' }}
                </button>
                <button @click="patchUser(u, { is_disabled: !u.is_disabled })" :disabled="updatingUser.has(u.id)"
                  class="ml-2 px-3 py-1.5 rounded-xl text-xs font-semibold transition disabled:opacity-50"
                  :class="u.is_disabled ? 'bg-emerald-50 text-emerald-600 hover:bg-emerald-100' : 'bg-red-50 text-red-600 hover:bg-red-100'">
                  {{ u.is_disabled ? '解禁' : '禁用' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- ============ AI 统计 ============ -->
    <template v-else>
      <div class="flex gap-2 mb-4 items-center">
        <select v-model.number="statsDays" @change="loadStats"
          class="px-4 py-2.5 rounded-2xl bg-white border border-neutral-200 outline-none text-sm focus:border-accent-500">
          <option :value="7">最近 7 天</option>
          <option :value="30">最近 30 天</option>
          <option :value="90">最近 90 天</option>
        </select>
        <span class="text-xs text-soft">统计口径：UTC 日 · 按 DeepSeek 官方定价估算</span>
      </div>
      <StateBlock v-if="statsLoading" status="loading" />
      <StateBlock v-else-if="statsError" status="error" :message="'统计加载失败：' + statsError" @retry="loadStats" />
      <StateBlock v-else-if="!stats || !stats.total_calls" status="empty" icon="fa-line-chart" message="统计区间内暂无 AI 调用" />
      <template v-else>
        <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
          <div class="rounded-3xl bg-white border border-neutral-100 shadow-card p-5">
            <i class="fa fa-commenting text-xl text-accent-400"></i>
            <div class="text-2xl font-extrabold mt-2">{{ fmtNum(stats.total_calls) }}</div>
            <div class="text-xs text-soft mt-0.5">调用次数</div>
          </div>
          <div class="rounded-3xl bg-white border border-neutral-100 shadow-card p-5">
            <i class="fa fa-inbox text-xl text-accent-400"></i>
            <div class="text-2xl font-extrabold mt-2">{{ fmtNum(stats.total_prompt_tokens) }}</div>
            <div class="text-xs text-soft mt-0.5">输入 tokens</div>
          </div>
          <div class="rounded-3xl bg-white border border-neutral-100 shadow-card p-5">
            <i class="fa fa-outbox text-xl text-accent-400"></i>
            <div class="text-2xl font-extrabold mt-2">{{ fmtNum(stats.total_completion_tokens) }}</div>
            <div class="text-xs text-soft mt-0.5">输出 tokens</div>
          </div>
          <div class="rounded-3xl bg-gradient-to-br from-accent-400 to-accent-600 text-white shadow-[0_10px_24px_rgba(255,107,44,.35)] p-5">
            <i class="fa fa-dollar text-xl opacity-80"></i>
            <div class="text-2xl font-extrabold mt-2">${{ stats.total_cost_usd.toFixed(4) }}</div>
            <div class="text-xs opacity-80 mt-0.5">估算成本</div>
          </div>
        </div>

        <div class="grid lg:grid-cols-2 gap-4">
          <div class="rounded-3xl bg-white border border-neutral-100 shadow-card p-5">
            <div class="text-sm font-bold mb-3">按场景</div>
            <table class="w-full text-sm">
              <thead>
                <tr class="text-left text-xs text-soft border-b border-neutral-100">
                  <th class="py-2 font-semibold">场景</th>
                  <th class="py-2 font-semibold">次数</th>
                  <th class="py-2 font-semibold hidden md:table-cell">输入 / 输出</th>
                  <th class="py-2 font-semibold text-right">成本</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in stats.by_scene" :key="s.scene" class="border-b border-neutral-50 last:border-0">
                  <td class="py-2 font-medium">{{ s.scene }}</td>
                  <td class="py-2 text-soft">{{ fmtNum(s.calls) }}</td>
                  <td class="py-2 text-xs text-soft hidden md:table-cell">{{ fmtNum(s.prompt_tokens) }} / {{ fmtNum(s.completion_tokens) }}</td>
                  <td class="py-2 text-right">${{ s.cost_usd.toFixed(4) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="rounded-3xl bg-white border border-neutral-100 shadow-card p-5">
            <div class="text-sm font-bold mb-3">按天</div>
            <table class="w-full text-sm">
              <thead>
                <tr class="text-left text-xs text-soft border-b border-neutral-100">
                  <th class="py-2 font-semibold">日期</th>
                  <th class="py-2 font-semibold">次数</th>
                  <th class="py-2 font-semibold text-right">成本</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="d in stats.by_day" :key="d.day" class="border-b border-neutral-50 last:border-0">
                  <td class="py-2 font-medium">{{ d.day }}</td>
                  <td class="py-2 text-soft">{{ fmtNum(d.calls) }}</td>
                  <td class="py-2 text-right">${{ d.cost_usd.toFixed(4) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>
