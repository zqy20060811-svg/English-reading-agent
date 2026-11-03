<script setup lang="ts">
// AI 悬浮按钮：可拖动 + 位置记忆，拖动结束的松手不触发点击（父组件用 v-show 控制显隐）
import { onMounted, ref } from 'vue'

const emit = defineEmits<{ toggle: [] }>()

const fab = ref<HTMLElement | null>(null)
const fabStyle = ref<Record<string, string>>({})
let dragMoved = false
let drag: { sx: number; sy: number; ox: number; oy: number } | null = null
const FAB_POS_KEY = 'era_ai_fab_pos'

function onPointerDown(e: PointerEvent): void {
  const el = fab.value!
  const r = el.getBoundingClientRect()
  drag = { sx: e.clientX, sy: e.clientY, ox: r.left, oy: r.top }
  el.setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent): void {
  if (!drag) return
  const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy
  if (Math.abs(dx) + Math.abs(dy) > 6) {
    dragMoved = true
    const x = Math.min(Math.max(8, drag.ox + dx), window.innerWidth - fab.value!.offsetWidth - 8)
    const y = Math.min(Math.max(8, drag.oy + dy), window.innerHeight - fab.value!.offsetHeight - 8)
    fabStyle.value = { left: x + 'px', top: y + 'px' }
  }
}

function onPointerUp(): void {
  if (dragMoved) {
    localStorage.setItem(FAB_POS_KEY, JSON.stringify({ x: fab.value!.offsetLeft, y: fab.value!.offsetTop }))
  }
  drag = null
}

function onClick(): void {
  if (dragMoved) { dragMoved = false; return }
  emit('toggle')
}

onMounted(() => {
  try {
    const saved = JSON.parse(localStorage.getItem(FAB_POS_KEY) || 'null')
    if (saved && typeof saved.x === 'number') fabStyle.value = { left: saved.x + 'px', top: saved.y + 'px' }
  } catch { /* 位置数据损坏则忽略 */ }
})
</script>

<template>
  <button ref="fab" @click="onClick"
    @pointerdown="onPointerDown" @pointermove="onPointerMove" @pointerup="onPointerUp"
    title="AI 助手（问答 / 翻译），可拖动"
    class="fixed right-6 bottom-8 z-40 w-14 h-14 rounded-full bg-gradient-to-br from-accent-400 to-accent-600 text-white shadow-[0_14px_34px_rgba(255,107,44,.5)] flex items-center justify-center text-xl hover:scale-105 transition"
    :style="{ ...fabStyle, touchAction: 'none', userSelect: 'none', cursor: 'grab' }">
    <i class="fa fa-magic"></i>
  </button>
</template>
