import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// 开发服务器跑在 5173，后端 FastAPI 在 8002（CORS 已放行 localhost 任意端口）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
  },
  // vitest：happy-dom 轻量 DOM 环境
  test: {
    environment: 'happy-dom',
    globals: false,
  },
})
