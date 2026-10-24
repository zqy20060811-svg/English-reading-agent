<script setup>
import AppSidebar from './components/AppSidebar.vue'
import ToastHost from './components/ToastHost.vue'
</script>

<template>
  <!-- 登录页独立布局，其余页面带深色侧边栏 -->
  <router-view v-if="$route.name === 'login'" />
  <div v-else class="min-h-screen flex">
    <AppSidebar />
    <main class="flex-1 min-w-0 ml-24 lg:ml-28">
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
  <ToastHost />
</template>
