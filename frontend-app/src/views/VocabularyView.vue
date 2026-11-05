<script setup lang="ts">
// 生词本：主流词典 App 样式——自定义分组筛选、按日期分组可折叠、
// 顶部筛选、发音按钮（浏览器 TTS）、批量释义懒加载；沿用项目现有视觉风格
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, apiErrorMessage } from '../api/client'
import { toast } from '../store'
import type { VocabItem, VocabGroup, VocabDefinitions, WordLookup } from '../types'
import StateBlock from '../components/StateBlock.vue'

const router = useRouter()

const loading = ref(true)
const error = ref('') // 加载失败信息（非空展示重试）
const words = ref<VocabItem[]>([])
const groups = ref<VocabGroup[]>([])
const removing = ref<Set<number>>(new Set())
const filter = ref('') // 顶部筛选：匹配单词 / 释义 / 来源书
const activeGroupId = ref<number | 'all' | 'none'>('all') // 分组筛选
const collapsed = ref<Set<string>>(new Set()) // 已折叠的日期分组
const defs = ref<Record<string, WordLookup | null>>({}) // word → 释义（批量接口懒加载）
const defsLoading = ref(false)

// 分组管理面板
const manageOpen = ref(false)
const newGroupName = ref('')
const creating = ref(false)
const renaming = ref<number | null>(null) // 正在重命名的分组 id
const renameValue = ref('')

async function loadWords(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    ;[words.value, groups.value] = await Promise.all([
      api<VocabItem[]>('/vocabulary'),
      api<VocabGroup[]>('/vocabulary/groups'),
    ])
    await loadDefinitions()
  } catch (err) {
    error.value = apiErrorMessage(err)
  } finally {
    loading.value = false
  }
}

async function loadGroups(): Promise<void> {
  groups.value = await api<VocabGroup[]>('/vocabulary/groups')
}

// 批量拉取释义：收藏过的词大多在阅读时查过（缓存命中零模型成本）
async function loadDefinitions(): Promise<void> {
  if (!words.value.length) return
  defsLoading.value = true
  try {
    const res = await api<VocabDefinitions>('/vocabulary/definitions', {
      method: 'POST',
      body: { words: words.value.map(w => w.word) },
    })
    defs.value = res.definitions
    if (res.llm_queried.length) {
      toast(`已联网补充 ${res.llm_queried.length} 个新词释义`, 'ok')
    }
  } catch {
    // 释义拉取失败不阻塞列表：行内显示"释义待查"，点击单词可单独查
  } finally {
    defsLoading.value = false
  }
}

onMounted(loadWords)

async function removeWord(item: VocabItem) {
  if (removing.value.has(item.id)) return
  removing.value.add(item.id)
  try {
    await api(`/vocabulary/${item.id}`, { method: 'DELETE' })
    words.value = words.value.filter(w => w.id !== item.id)
    await loadGroups() // 词数刷新
    toast(`已移除「${item.word}」`, 'ok')
  } catch (err) {
    toast('移除失败：' + apiErrorMessage(err))
  } finally {
    removing.value.delete(item.id)
  }
}

// ---------- 分组操作 ----------
async function createGroup(): Promise<void> {
  const name = newGroupName.value.trim()
  if (!name) return
  if (creating.value) return
  creating.value = true
  try {
    const g = await api<VocabGroup>('/vocabulary/groups', {
      method: 'POST',
      body: { name },
    })
    groups.value.push(g)
    newGroupName.value = ''
    toast(`已创建分组「${name}」`, 'ok')
  } catch (err) {
    toast('创建失败：' + apiErrorMessage(err))
  } finally {
    creating.value = false
  }
}

async function renameGroup(g: VocabGroup): Promise<void> {
  const name = renameValue.value.trim()
  if (!name || name === g.name) {
    renaming.value = null
    return
  }
  try {
    const updated = await api<VocabGroup>(`/vocabulary/groups/${g.id}`, {
      method: 'PATCH',
      body: { name },
    })
    const i = groups.value.findIndex(x => x.id === g.id)
    if (i >= 0) groups.value[i] = updated
    renaming.value = null
    toast('已重命名', 'ok')
  } catch (err) {
    toast('重命名失败：' + apiErrorMessage(err))
  }
}

async function deleteGroup(g: VocabGroup): Promise<void> {
  if (!confirm(`删除分组「${g.name}」？组内 ${g.word_count} 个生词将回到未分组，不会丢失。`)) return
  try {
    await api(`/vocabulary/groups/${g.id}`, { method: 'DELETE' })
    groups.value = groups.value.filter(x => x.id !== g.id)
    if (activeGroupId.value === g.id) activeGroupId.value = 'all'
    await loadWords() // 词的 group_id 变了，整页刷新最稳
    toast(`已删除分组「${g.name}」`, 'ok')
  } catch (err) {
    toast('删除失败：' + apiErrorMessage(err))
  }
}

async function moveWord(item: VocabItem, groupId: number | null): Promise<void> {
  try {
    await api(`/vocabulary/${item.id}/group`, {
      method: 'PATCH',
      body: { group_id: groupId },
    })
    const i = words.value.findIndex(w => w.id === item.id)
    if (i >= 0) words.value[i] = { ...words.value[i], group_id: groupId }
    await loadGroups()
    const target = groups.value.find(g => g.id === groupId)
    toast(groupId === null ? `已移出分组` : `已移入「${target?.name ?? ''}」`, 'ok')
  } catch (err) {
    toast('移动失败：' + apiErrorMessage(err))
  }
}

function startRename(g: VocabGroup): void {
  renaming.value = g.id
  renameValue.value = g.name
}

// ---------- 日期分组（今天 / 昨天 / 具体日期） ----------
interface Group { key: string; label: string; items: VocabItem[] }

const activeGroup = computed(() => groups.value.find(g => g.id === activeGroupId.value) ?? null)

const filteredWords = computed(() => {
  // 先按分组筛选
  let list = words.value
  if (activeGroupId.value === 'none') list = list.filter(w => w.group_id === null)
  else if (typeof activeGroupId.value === 'number')
    list = list.filter(w => w.group_id === activeGroupId.value)
  // 再按关键词筛选
  const kw = filter.value.trim().toLowerCase()
  if (!kw) return list
  return list.filter(w => {
    const d = defs.value[w.word]
    const defText = d ? d.senses.join(' ') : ''
    return (
      w.word.includes(kw) ||
      defText.toLowerCase().includes(kw) ||
      w.book_title.toLowerCase().includes(kw)
    )
  })
})

const groups_ = computed<Group[]>(() => {
  const byDay = new Map<string, VocabItem[]>()
  for (const w of filteredWords.value) {
    const key = new Date(w.created_at).toLocaleDateString('sv-SE') // YYYY-MM-DD
    const list = byDay.get(key)
    if (list) list.push(w)
    else byDay.set(key, [w])
  }
  const today = new Date().toLocaleDateString('sv-SE')
  const yesterday = new Date(Date.now() - 86400000).toLocaleDateString('sv-SE')
  return [...byDay.entries()].map(([key, items]) => ({
    key,
    label:
      key === today ? `今天 (${items.length})`
      : key === yesterday ? `昨天 (${items.length})`
      : `${key} (${items.length})`,
    items,
  }))
})

function toggleGroup(key: string): void {
  const next = new Set(collapsed.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsed.value = next
}

// ---------- 发音（浏览器 TTS，无额外成本） ----------
function speak(word: string): void {
  if (!('speechSynthesis' in window)) {
    toast('当前浏览器不支持语音朗读')
    return
  }
  window.speechSynthesis.cancel()
  const u = new SpeechSynthesisUtterance(word)
  u.lang = 'en-US'
  u.rate = 0.9
  window.speechSynthesis.speak(u)
}
</script>

<template>
  <div class="p-6 lg:p-10 max-w-3xl mx-auto">
    <div class="flex items-end justify-between flex-wrap gap-3">
      <div>
        <h2 class="text-2xl font-extrabold">生词本</h2>
        <p class="text-sm text-soft mt-1">阅读时点击单词查义后即可收录，共 {{ words.length }} 个生词</p>
      </div>
      <div class="flex gap-2">
        <button @click="manageOpen = !manageOpen"
          class="px-4 py-2 rounded-2xl bg-white border text-sm transition"
          :class="manageOpen ? 'border-accent-400 text-accent-600' : 'border-neutral-200 text-neutral-600 hover:border-accent-400 hover:text-accent-600'">
          <i class="fa fa-folder-o mr-1"></i>分组管理
        </button>
        <button @click="router.push('/')"
          class="px-4 py-2 rounded-2xl bg-white border border-neutral-200 text-sm text-neutral-600 hover:border-accent-400 hover:text-accent-600 transition">
          <i class="fa fa-plus mr-1"></i>去阅读收录
        </button>
      </div>
    </div>

    <!-- 分组筛选栏 -->
    <div v-if="words.length" class="mt-5 flex gap-2 overflow-x-auto pb-1 -mx-1 px-1">
      <button @click="activeGroupId = 'all'"
        class="shrink-0 px-3.5 py-1.5 rounded-full text-sm border transition"
        :class="activeGroupId === 'all' ? 'bg-neutral-800 text-white border-neutral-800' : 'bg-white border-neutral-200 text-neutral-600 hover:border-neutral-400'">
        全部 ({{ words.length }})
      </button>
      <button v-for="g in groups" :key="g.id" @click="activeGroupId = g.id"
        class="shrink-0 px-3.5 py-1.5 rounded-full text-sm border transition"
        :class="activeGroupId === g.id ? 'bg-accent-500 text-white border-accent-500' : 'bg-white border-neutral-200 text-neutral-600 hover:border-accent-400'">
        {{ g.name }} ({{ g.word_count }})
      </button>
      <button @click="activeGroupId = 'none'"
        class="shrink-0 px-3.5 py-1.5 rounded-full text-sm border transition"
        :class="activeGroupId === 'none' ? 'bg-neutral-800 text-white border-neutral-800' : 'bg-white border-neutral-200 text-neutral-600 hover:border-neutral-400'">
        未分组 ({{ words.filter(w => w.group_id === null).length }})
      </button>
    </div>

    <!-- 分组管理面板 -->
    <div v-if="manageOpen" class="mt-4 p-4 rounded-2xl bg-white border border-neutral-200 shadow-card">
      <div class="text-sm font-bold mb-3">分组管理</div>
      <!-- 新建 -->
      <div class="flex gap-2 mb-3">
        <input v-model="newGroupName" type="text" maxlength="32" placeholder="新分组名称，如：重点词、单元1"
          class="flex-1 px-4 py-2.5 rounded-xl bg-neutral-50 border border-neutral-200 text-sm placeholder:text-neutral-300 focus:outline-none focus:border-accent-400 transition"
          @keydown.enter="createGroup" />
        <button :disabled="creating || !newGroupName.trim()"
          @click="createGroup"
          class="px-4 py-2.5 rounded-xl bg-accent-500 text-white text-sm font-bold hover:bg-accent-600 transition disabled:opacity-40 disabled:cursor-not-allowed">
          <i class="fa fa-plus mr-1"></i>新建
        </button>
      </div>
      <!-- 组列表 -->
      <div v-if="groups.length" class="space-y-1.5">
        <div v-for="g in groups" :key="g.id"
          class="flex items-center gap-2 px-3 py-2 rounded-xl bg-neutral-50 border border-neutral-100">
          <i class="fa fa-folder text-accent-400 text-sm"></i>
          <template v-if="renaming === g.id">
            <input v-model="renameValue" type="text" maxlength="32"
              class="flex-1 px-2.5 py-1.5 rounded-lg bg-white border border-accent-300 text-sm focus:outline-none"
              @keydown.enter="renameGroup(g)" @keydown.esc="renaming = null" />
            <button @click="renameGroup(g)" title="保存"
              class="w-7 h-7 rounded-lg text-green-600 hover:bg-green-50 transition"><i class="fa fa-check text-xs"></i></button>
            <button @click="renaming = null" title="取消"
              class="w-7 h-7 rounded-lg text-neutral-400 hover:bg-neutral-100 transition"><i class="fa fa-times text-xs"></i></button>
          </template>
          <template v-else>
            <span class="flex-1 text-sm font-bold">{{ g.name }}</span>
            <span class="text-xs text-soft">{{ g.word_count }} 词</span>
            <button @click="startRename(g)" title="重命名"
              class="w-7 h-7 rounded-lg text-neutral-400 hover:text-accent-600 hover:bg-accent-50 transition"><i class="fa fa-pencil text-xs"></i></button>
            <button @click="deleteGroup(g)" title="删除分组（组内词回到未分组）"
              class="w-7 h-7 rounded-lg text-neutral-400 hover:text-red-500 hover:bg-red-50 transition"><i class="fa fa-trash text-xs"></i></button>
          </template>
        </div>
      </div>
      <p v-else class="text-xs text-soft">还没有分组，先新建一个吧</p>
    </div>

    <!-- 顶部关键词筛选 -->
    <div v-if="words.length" class="mt-4">
      <div class="relative">
        <i class="fa fa-search absolute left-4 top-1/2 -translate-y-1/2 text-neutral-300 text-sm"></i>
        <input v-model="filter" type="text" placeholder="筛选当前列表中的单词"
          class="w-full pl-10 pr-4 py-3 rounded-2xl bg-white border border-neutral-200 text-sm placeholder:text-neutral-300 focus:outline-none focus:border-accent-400 transition" />
        <button v-if="filter" @click="filter = ''" title="清空筛选"
          class="absolute right-3 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full text-neutral-300 hover:text-neutral-500 hover:bg-neutral-100 transition">
          <i class="fa fa-times text-xs"></i>
        </button>
      </div>
    </div>

    <StateBlock v-if="loading" status="loading" />
    <StateBlock v-else-if="error" status="error" :message="'生词本加载失败：' + error" @retry="loadWords" />

    <StateBlock v-else-if="!words.length" status="empty" icon="fa-language" message="生词本还是空的" hint="阅读时点击生词，释义卡片里可一键收藏" />

    <StateBlock v-else-if="!groups_.length" status="empty" icon="fa-search"
      :message="filter ? '没有匹配的生词' : activeGroup ? `分组「${activeGroup.name}」还没有生词` : '该分组下暂无生词'"
      :hint="filter ? '换个关键词试试' : '点击生词卡片右下角按钮移动到这里'" />

    <!-- 按日期分组列表 -->
    <div v-else class="mt-4 space-y-5">
      <section v-for="g in groups_" :key="g.key">
        <!-- 组头：可折叠 -->
        <button @click="toggleGroup(g.key)"
          class="w-full flex items-center gap-2 px-3 py-2 text-sm font-bold text-neutral-500 hover:text-neutral-700 transition">
          <i class="fa fa-chevron-down text-xs transition-transform" :class="{ '-rotate-90': collapsed.has(g.key) }"></i>
          {{ g.label }}
        </button>

        <div v-show="!collapsed.has(g.key)" class="mt-1 space-y-2">
          <div v-for="w in g.items" :key="w.id"
            class="flex gap-3 items-start p-4 rounded-2xl bg-white border border-neutral-200 shadow-card">
            <!-- 发音按钮 -->
            <button @click="speak(w.word)" title="朗读单词"
              class="shrink-0 w-9 h-9 rounded-xl text-accent-500 hover:bg-accent-50 transition">
              <i class="fa fa-volume-up"></i>
            </button>

            <div class="min-w-0 flex-1">
              <!-- 单词 + 音标 -->
              <div class="flex items-baseline gap-2 flex-wrap">
                <span class="book-title text-lg font-bold">{{ w.word }}</span>
                <span v-if="defs[w.word]?.phonetic" class="text-xs text-soft">{{ defs[w.word]!.phonetic }}</span>
                <span v-if="w.group_id !== null" class="text-xs px-2 py-0.5 rounded-full bg-accent-50 text-accent-600">
                  {{ groups.find(x => x.id === w.group_id)?.name ?? '' }}
                </span>
              </div>
              <!-- 释义（批量懒加载；无则提示） -->
              <p v-if="defs[w.word]?.senses?.length" class="text-sm text-neutral-600 mt-1 leading-relaxed">
                {{ defs[w.word]!.senses.join('；') }}
              </p>
              <p v-else-if="defsLoading" class="text-xs text-soft mt-1 animate-pulse">释义加载中…</p>
              <p v-else class="text-xs text-soft mt-1">释义暂无，<router-link to="/" class="text-accent-600 hover:underline">去阅读</router-link>点击该词可查询</p>

              <!-- 来源与例句 -->
              <div class="text-xs text-soft mt-1.5">来自《{{ w.book_title || '个人书籍' }}》 · 第 {{ w.chapter_index }} 章</div>
              <p v-if="w.context_sentence" class="text-xs text-neutral-500 mt-1.5 bg-neutral-50 rounded-xl px-3 py-2 leading-relaxed">
                {{ w.context_sentence }}
              </p>

              <!-- 移动到分组 -->
              <div class="mt-2 flex items-center gap-1.5 flex-wrap">
                <i class="fa fa-folder-o text-neutral-300 text-xs"></i>
                <button v-if="w.group_id !== null" @click="moveWord(w, null)"
                  class="text-xs px-2.5 py-1 rounded-full bg-neutral-100 text-neutral-500 hover:bg-neutral-200 transition">
                  移出分组
                </button>
                <template v-for="g2 in groups" :key="g2.id">
                  <button v-if="w.group_id !== g2.id" @click="moveWord(w, g2.id)"
                    class="text-xs px-2.5 py-1 rounded-full bg-neutral-50 border border-neutral-200 text-neutral-500 hover:border-accent-400 hover:text-accent-600 transition">
                    → {{ g2.name }}
                  </button>
                </template>
              </div>
            </div>

            <button :disabled="removing.has(w.id)" @click="removeWord(w)" title="移除生词"
              class="shrink-0 w-9 h-9 rounded-xl text-neutral-300 hover:text-red-500 hover:bg-red-50 transition disabled:opacity-40">
              <i class="fa fa-trash"></i>
            </button>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
