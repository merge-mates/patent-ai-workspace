import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type Plugin } from 'vite'

// 시연용 실제 결과(web/.demo/, git 밖)를 읽는 가상 모듈.
// VITE_DEMO=1일 때만 파일 목록을 만든다. 아니면 빈 목록이라 파일 이름조차 코드에 안 들어간다.
function demoResults(enabled: boolean): Plugin {
  const id = 'virtual:demo-results'
  return {
    name: 'demo-results',
    resolveId: (source) => (source === id ? `\0${id}` : null),
    load: (resolved) => {
      if (resolved !== `\0${id}`) return null
      return enabled
        ? "export default import.meta.glob('/.demo/*.json', { import: 'default' })"
        : 'export default {}'
    },
  }
}

// 화면은 /api/* 로 부르고, 개발 서버가 FastAPI로 넘긴다 (CORS 설정 없이).
// 넘길 주소는 API_PROXY_TARGET (docker compose에서는 http://api:8000).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const demo = env.VITE_DEMO === '1'
  return {
    plugins: [react(), demoResults(demo)],
    server: {
      // 시연 모드는 실제 사건 자료를 다루므로 이 컴퓨터에서만 열린다 (같은 망에서 못 받게)
      host: demo ? '127.0.0.1' : true,
      port: 5173,
      // 시연 모드가 아니면 .demo 폴더 파일을 아예 내주지 않는다
      fs: demo ? undefined : { deny: ['.env', '.env.*', '*.{crt,pem}', '**/.git/**', '**/.demo/**'] },
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
