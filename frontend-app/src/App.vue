<script setup lang="ts">
import AppSidebar from './components/AppSidebar.vue'
import MobileTabBar from './components/MobileTabBar.vue'
import ToastHost from './components/ToastHost.vue'
</script>

<template>
  <!-- 登录页独立布局；桌面端左侧深色侧边栏，移动端底部 Tab 导航 -->
  <router-view v-if="$route.name === 'login'" />
  <div v-else class="min-h-screen flex">
    <AppSidebar />
    <main class="flex-1 min-w-0 lg:ml-24 pb-20 lg:pb-0">
      <router-view v-slot="{ Component }">
        <transition name="page" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
  <MobileTabBar />
  <ToastHost />
</template>
