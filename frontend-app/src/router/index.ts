import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api/client'
import { loadMe, store } from '../store'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/', name: 'library', component: () => import('../views/LibraryView.vue') },
  { path: '/rank', name: 'rank', component: () => import('../views/RankView.vue') },
  { path: '/shelf', name: 'shelf', component: () => import('../views/ShelfView.vue') },
  { path: '/upload', name: 'upload', component: () => import('../views/UploadView.vue') },
  // 个人书籍阅读器：与公共书同组件，按路由名切换 API 来源（/personal/books）
  { path: '/read/personal/:bookId', name: 'reader-personal', component: () => import('../views/ReaderView.vue') },
  { path: '/read/:bookId?', name: 'reader', component: () => import('../views/ReaderView.vue') },
  { path: '/test', name: 'test', component: () => import('../views/TestView.vue') },
  { path: '/translate', name: 'translate', component: () => import('../views/TranslateView.vue') },
  { path: '/vocabulary', name: 'vocabulary', component: () => import('../views/VocabularyView.vue') },
  { path: '/profile', name: 'profile', component: () => import('../views/PersonalView.vue') },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue') },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('../views/AdminView.vue'),
    // 路由级守卫：仅管理员可进（刷新后先补拉 /me 再判断）
    beforeEnter: async () => {
      const me = store.me || (await loadMe())
      if (!me?.is_admin) return { name: 'library' }
    },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 未登录统一回登录页；已登录访问登录页直接进书库
router.beforeEach(to => {
  const logged = !!getToken()
  if (!logged && to.name !== 'login') return { name: 'login' }
  if (logged && to.name === 'login') return { name: 'library' }
})

export default router
