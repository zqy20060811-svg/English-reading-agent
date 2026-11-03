/// <reference types="vite/client" />

// Vite 环境变量类型声明
interface ImportMetaEnv {
  readonly VITE_API_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
