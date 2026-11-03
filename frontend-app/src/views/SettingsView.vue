<script setup>
// 设置页：修改密码 + 翻译默认目标语言（保存到服务端，翻译页自动生效）
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, logout } from '../api/client'
import { toast } from '../store'

const router = useRouter()

// 修改密码
const oldPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')
const changing = ref(false)

// 翻译默认目标语言（与翻译页 LANG_PROMPTS 表述保持一致）
const LANG_PROMPTS = { zh: '中文', en: 'English', ja: '日语', ko: '韩语', fr: '法语', de: '德语', es: '西班牙语', ru: '俄语' }
const PROMPT_TO_CODE = Object.fromEntries(Object.entries(LANG_PROMPTS).map(([code, name]) => [name, code]))
const targetLangCode = ref('zh')
const savingLang = ref(false)
const confirmLogout = ref(false) // 两段式确认：第一次点击进入待确认状态

function doLogout() {
  logout()
  router.replace('/login')
}

onMounted(async () => {
  try {
    const s = await api('/me/settings')
    if (PROMPT_TO_CODE[s.target_lang]) targetLangCode.value = PROMPT_TO_CODE[s.target_lang]
  } catch { /* 读取失败保持默认，保存时可再试 */ }
})

async function changePassword() {
  if (!oldPwd.value || !newPwd.value) { toast('请填写完整'); return }
  if (newPwd.value.length < 6) { toast('新密码至少 6 位'); return }
  if (newPwd.value !== confirmPwd.value) { toast('两次输入的新密码不一致'); return }
  changing.value = true
  try {
    await api('/me/password', { method: 'PUT', body: { old_password: oldPwd.value, new_password: newPwd.value } })
    toast('密码修改成功，请重新登录', 'success')
    setTimeout(() => {
      logout()
      router.replace('/login')
    }, 1200)
  } catch (err) {
    toast('修改失败：' + err.message)
  } finally {
    changing.value = false
  }
}

async function saveLang() {
  savingLang.value = true
  try {
    await api('/me/settings', { method: 'PUT', body: { target_lang: LANG_PROMPTS[targetLangCode.value] } })
    toast('已保存，翻译页将默认使用该语言', 'success')
  } catch (err) {
    toast('保存失败：' + err.message)
  } finally {
    savingLang.value = false
  }
}
</script>

<template>
  <div class="p-6 lg:p-10 max-w-2xl mx-auto">
    <h2 class="text-2xl font-extrabold flex items-center gap-2">
      <i class="fa fa-cog text-accent-500"></i>设置
    </h2>
    <p class="text-sm text-soft mt-1">账号安全与阅读偏好</p>

    <!-- 修改密码 -->
    <section class="mt-8 rounded-2xl bg-white border border-neutral-100 shadow-card p-6">
      <h3 class="font-bold"><i class="fa fa-lock mr-2 text-neutral-400"></i>修改密码</h3>
      <div class="mt-4 flex flex-col gap-3">
        <input v-model="oldPwd" type="password" placeholder="当前密码"
          class="px-4 py-2.5 rounded-xl bg-neutral-50 border border-neutral-200 outline-none text-sm focus:border-accent-500" />
        <input v-model="newPwd" type="password" placeholder="新密码（至少 6 位）"
          class="px-4 py-2.5 rounded-xl bg-neutral-50 border border-neutral-200 outline-none text-sm focus:border-accent-500" />
        <input v-model="confirmPwd" type="password" placeholder="确认新密码"
          class="px-4 py-2.5 rounded-xl bg-neutral-50 border border-neutral-200 outline-none text-sm focus:border-accent-500" />
        <button :disabled="changing" @click="changePassword"
          class="self-start px-5 py-2 rounded-full bg-accent-500 text-white text-xs font-semibold hover:bg-accent-600 transition disabled:opacity-50">
          {{ changing ? '提交中...' : '确认修改' }}
        </button>
        <p class="text-xs text-soft">修改成功后需使用新密码重新登录。</p>
      </div>
    </section>

    <!-- 翻译偏好 -->
    <section class="mt-6 rounded-2xl bg-white border border-neutral-100 shadow-card p-6">
      <h3 class="font-bold"><i class="fa fa-language mr-2 text-neutral-400"></i>翻译默认语言</h3>
      <div class="mt-4 flex items-center gap-3">
        <select v-model="targetLangCode"
          class="appearance-none px-4 py-2.5 rounded-xl bg-neutral-50 border border-neutral-200 outline-none text-sm focus:border-accent-500 cursor-pointer">
          <option v-for="(name, code) in LANG_PROMPTS" :key="code" :value="code">{{ name }}</option>
        </select>
        <button :disabled="savingLang" @click="saveLang"
          class="px-5 py-2 rounded-full bg-accent-500 text-white text-xs font-semibold hover:bg-accent-600 transition disabled:opacity-50">
          {{ savingLang ? '保存中...' : '保存' }}
        </button>
      </div>
      <p class="text-xs text-soft mt-3">保存后，翻译页的目标语言将默认选中此项。</p>
    </section>

    <!-- 退出登录 -->
    <section class="mt-6 rounded-2xl bg-white border border-red-100 shadow-card p-6">
      <h3 class="font-bold text-red-500"><i class="fa fa-sign-out mr-2"></i>退出登录</h3>
      <div class="mt-3 flex items-center gap-3 flex-wrap">
        <button @click="confirmLogout ? doLogout() : (confirmLogout = true)"
          class="px-5 py-2 rounded-full text-xs font-semibold border transition"
          :class="confirmLogout
            ? 'bg-red-500 border-red-500 text-white hover:bg-red-600'
            : 'bg-white border-red-200 text-red-500 hover:bg-red-50'">
          {{ confirmLogout ? '再点一次确认退出' : '退出登录' }}
        </button>
        <span v-if="confirmLogout" class="text-xs text-soft">退出后需要重新登录才能继续阅读</span>
      </div>
    </section>
  </div>
</template>
