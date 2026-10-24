import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发服务器跑在 5173，后端 FastAPI 在 8002（CORS 已放行 localhost 任意端口）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
  },
})
