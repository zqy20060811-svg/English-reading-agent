<script setup lang="ts">
// 通用三态块：加载中 / 空数据 / 失败重试，统一各页面的占位视觉
withDefaults(defineProps<{
  status: 'loading' | 'empty' | 'error'
  /** 失败或空态的主文案；空态默认「暂无内容」 */
  message?: string
  /** 空态的次要提示 */
  hint?: string
  /** 空态图标（Font Awesome 类名） */
  icon?: string
  /** 失败态是否显示重试按钮（默认显示） */
  retryable?: boolean
}>(), { retryable: true })

defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="py-20 text-center text-soft">
    <!-- 加载中 -->
    <template v-if="status === 'loading'">
      <i class="fa fa-circle-o-notch fa-spin text-2xl"></i>
      <p class="mt-3 text-sm">{{ message || '加载中...' }}</p>
    </template>
    <!-- 加载失败：可重试 -->
    <template v-else-if="status === 'error'">
      <i class="fa fa-exclamation-triangle text-4xl opacity-30"></i>
      <p class="mt-4 text-sm">{{ message || '加载失败，请稍后重试' }}</p>
      <button v-if="retryable" @click="$emit('retry')"
        class="mt-4 px-5 py-2 rounded-full bg-accent-500 text-white text-xs font-semibold hover:bg-accent-600 transition">
        <i class="fa fa-refresh mr-1.5"></i>重新加载
      </button>
    </template>
    <!-- 空数据 -->
    <template v-else>
      <i class="text-4xl opacity-30" :class="icon || 'fa-inbox'"></i>
      <p class="mt-4 text-sm">{{ message || '暂无内容' }}</p>
      <p v-if="hint" class="mt-1 text-xs">{{ hint }}</p>
      <slot />
    </template>
  </div>
</template>
