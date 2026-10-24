<script setup>
// 登录 / 注册（沿用现有接口与交互，按新设计语言重绘）
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, TOKEN_KEY, USER_KEY } from '../api/client'
import { toast } from '../store'

const router = useRouter()
const tab = ref('login')
const alert = ref(null) // { type: 'error'|'ok', text }
const loading = ref(false)

const loginForm = ref({ username: '', password: '' })
const registerForm = ref({ username: '', email: '', password: '' })

function switchTab(t) {
  tab.value = t
  alert.value = null
}

function showAlert(type, text) {
  alert.value = { type, text }
}

async function doLogin() {
  alert.value = null
  loading.value = true
  try {
    const token = await api('/auth/login', {
      method: 'POST',
      body: { username: loginForm.value.username.trim(), password: loginForm.value.password },
    })
    localStorage.setItem(TOKEN_KEY, token.access_token)
    localStorage.setItem(USER_KEY, loginForm.value.username.trim())
    router.replace('/')
  } catch (err) {
    showAlert('error', '登录失败：' + (err.message === 'Failed to fetch'
      ? '无法连接后端服务，请确认服务已启动（http://127.0.0.1:8002）'
      : err.message))
  } finally {
    loading.value = false
  }
}

async function doRegister() {
  alert.value = null
  loading.value = true
  try {
    const user = await api('/auth/register', {
      method: 'POST',
      body: {
        username: registerForm.value.username.trim(),
        email: registerForm.value.email.trim(),
        password: registerForm.value.password,
      },
    })
    loginForm.value.username = user.username
    tab.value = 'login'
    showAlert('ok', `注册成功，${user.username} 已自动填入用户名，请登录。`)
  } catch (err) {
    showAlert('error', '注册失败：' + err.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen flex items-center justify-center p-6"
    style="background: linear-gradient(160deg, #FFF7F0 0%, #FAFAF8 45%, #FFF3EB 100%)">
    <div class="w-full max-w-md">
      <!-- 品牌区 -->
      <div class="flex items-center gap-3 mb-8 justify-center">
        <div class="w-12 h-12 rounded-2xl bg-gradient-to-br from-accent-400 to-accent-600 flex items-center justify-center text-white text-xl shadow-[0_10px_24px_rgba(255,107,44,.45)]">
          <i class="fa fa-book"></i>
        </div>
        <div>
          <div class="text-xl font-extrabold">English Reading</div>
          <div class="text-xs text-soft">读英文书，学地道英语</div>
        </div>
      </div>

      <!-- 登录卡 -->
      <div class="rounded-3xl bg-white shadow-card p-8">
        <!-- 标签页 -->
        <div class="flex mb-6 rounded-2xl bg-neutral-100 p-1">
          <button @click="switchTab('login')"
            class="flex-1 py-2.5 rounded-xl text-sm font-semibold transition"
            :class="tab === 'login' ? 'bg-ink text-white shadow' : 'text-soft hover:text-ink'">
            登录
          </button>
          <button @click="switchTab('register')"
            class="flex-1 py-2.5 rounded-xl text-sm font-semibold transition"
            :class="tab === 'register' ? 'bg-ink text-white shadow' : 'text-soft hover:text-ink'">
            注册
          </button>
        </div>

        <!-- 提示条 -->
        <div v-if="alert" class="mb-4 rounded-xl p-3 text-sm animate-[shake_.4s_ease]"
          :class="alert.type === 'error'
            ? 'bg-red-50 border border-red-100 text-red-600'
            : 'bg-emerald-50 border border-emerald-100 text-emerald-700'">
          {{ alert.text }}
        </div>

        <!-- 登录表单 -->
        <form v-if="tab === 'login'" @submit.prevent="doLogin" class="space-y-4">
          <div>
            <label class="text-xs font-semibold text-soft mb-1.5 block">用户名</label>
            <input v-model="loginForm.username" required autocomplete="username" placeholder="请输入用户名"
              class="w-full px-4 py-3 rounded-2xl bg-neutral-50 border border-neutral-200 outline-none text-sm focus:border-accent-500 focus:bg-white transition" />
          </div>
          <div>
            <label class="text-xs font-semibold text-soft mb-1.5 block">密码</label>
            <input v-model="loginForm.password" type="password" required autocomplete="current-password" placeholder="请输入密码"
              class="w-full px-4 py-3 rounded-2xl bg-neutral-50 border border-neutral-200 outline-none text-sm focus:border-accent-500 focus:bg-white transition" />
          </div>
          <button type="submit" :disabled="loading"
            class="w-full py-3.5 rounded-2xl bg-accent-500 text-white font-semibold hover:bg-accent-600 transition disabled:opacity-60 shadow-[0_10px_24px_rgba(255,107,44,.35)]">
            <i v-if="loading" class="fa fa-circle-o-notch fa-spin mr-1"></i>
            {{ loading ? '请稍候...' : '登录，继续阅读' }}
          </button>
        </form>

        <!-- 注册表单 -->
        <form v-else @submit.prevent="doRegister" class="space-y-4">
          <div>
            <label class="text-xs font-semibold text-soft mb-1.5 block">用户名</label>
            <input v-model="registerForm.username" required placeholder="3-20 个字符"
              class="w-full px-4 py-3 rounded-2xl bg-neutral-50 border border-neutral-200 outline-none text-sm focus:border-accent-500 focus:bg-white transition" />
          </div>
          <div>
            <label class="text-xs font-semibold text-soft mb-1.5 block">邮箱</label>
            <input v-model="registerForm.email" type="email" required placeholder="name@example.com"
              class="w-full px-4 py-3 rounded-2xl bg-neutral-50 border border-neutral-200 outline-none text-sm focus:border-accent-500 focus:bg-white transition" />
          </div>
          <div>
            <label class="text-xs font-semibold text-soft mb-1.5 block">密码</label>
            <input v-model="registerForm.password" type="password" required placeholder="至少 6 位"
              class="w-full px-4 py-3 rounded-2xl bg-neutral-50 border border-neutral-200 outline-none text-sm focus:border-accent-500 focus:bg-white transition" />
          </div>
          <button type="submit" :disabled="loading"
            class="w-full py-3.5 rounded-2xl bg-accent-500 text-white font-semibold hover:bg-accent-600 transition disabled:opacity-60 shadow-[0_10px_24px_rgba(255,107,44,.35)]">
            <i v-if="loading" class="fa fa-circle-o-notch fa-spin mr-1"></i>
            {{ loading ? '请稍候...' : '注册，开始学习' }}
          </button>
        </form>
      </div>

      <p class="text-center text-xs text-soft mt-6">登录即代表同意服务条款与隐私政策 · 英语水平测试为初步评估，非官方 CEFR 认证</p>
    </div>
  </div>
</template>

<style scoped>
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-5px); }
  75% { transform: translateX(5px); }
}
.animate-\[shake_\.4s_ease\] {
  animation: shake .4s ease;
}
</style>
