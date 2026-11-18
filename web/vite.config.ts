import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// 화면은 /api/* 로 부르고, 개발 서버가 FastAPI로 넘긴다 (CORS 설정 없이).
// 넘길 주소는 API_PROXY_TARGET (docker compose에서는 http://api:8000).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      host: true,
      port: 5173,
      proxy: {
        '/api': {
          target: env.API_PROXY_TARGET ?? 'http://localhost:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
