import { createRouter, createWebHistory } from 'vue-router'
import { getToken } from '../api/client'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/', name: 'library', component: () => import('../views/LibraryView.vue') },
  { path: '/rank', name: 'rank', component: () => import('../views/RankView.vue') },
  { path: '/read/:bookId?', name: 'reader', component: () => import('../views/ReaderView.vue') },
  { path: '/test', name: 'test', component: () => import('../views/TestView.vue') },
  { path: '/translate', name: 'translate', component: () => import('../views/TranslateView.vue') },
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
