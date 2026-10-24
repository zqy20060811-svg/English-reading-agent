<script setup>
// 全局提示条（底部居中，自动消失）
import { store } from '../store'
</script>

<template>
  <div class="fixed bottom-8 left-1/2 z-[100] -translate-x-1/2 space-y-2">
    <transition-group name="toast">
      <div v-for="t in store.toasts" :key="t.id"
        class="rounded-xl px-6 py-3 text-sm text-white shadow-float"
        :class="t.type === 'error' ? 'bg-red-500' : 'bg-emerald-600'">
        {{ t.text }}
      </div>
    </transition-group>
  </div>
</template>
