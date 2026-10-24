/** @type {import('tailwindcss').Config} */
// 设计基调：白底 + 深色近黑面板 + 暖橙强调色 + 衬线斜体书名
export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      colors: {
        // 主强调色（截图中的暖橙：分类激活 pill / 进度条 / Logo）
        accent: {
          50: '#FFF3EB',
          100: '#FFE4D3',
          200: '#FFC7A6',
          400: '#FF8A50',
          500: '#FF6B2C',
          600: '#F55A17',
          700: '#D9480F',
        },
        // 深色面板（侧边栏 / 继续阅读大卡）
        ink: {
          DEFAULT: '#1A1A1A',
          800: '#242424',
          700: '#2E2E2E',
        },
        soft: '#8E8E93', // 次要文字灰
        paper: '#FAFAF8', // 主内容区底色
      },
      fontFamily: {
        // 书名衬线斜体（截图中的经典书卷气）
        serifTitle: ['Georgia', '"Times New Roman"', '"Songti SC"', 'serif'],
        sans: [
          'Inter', 'system-ui', '-apple-system', '"Segoe UI"', 'Roboto',
          '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', 'sans-serif',
        ],
      },
      boxShadow: {
        card: '0 12px 32px rgba(26, 26, 26, 0.08)',
        float: '0 18px 44px rgba(26, 26, 26, 0.16)',
      },
      borderRadius: {
        '2.5xl': '1.25rem',
        '3xl': '1.5rem',
      },
    },
  },
  plugins: [],
}
