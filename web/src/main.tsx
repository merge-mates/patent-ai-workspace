import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App as AntApp, ConfigProvider } from 'antd'
import koKR from 'antd/locale/ko_KR'
// 글꼴은 npm 패키지에서 로컬로 넣는다 (CDN 안 씀)
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import './index.css'
import App from './App.tsx'
import { router } from './router'
import { setRevalidate } from './runPoll'
import { appTheme } from './theme.ts'

// 폴링 모듈이 router를 직접 import하지 않도록 여기서 이어 준다 (순환 import 방지)
setRevalidate(() => void router.revalidate())

// 한국어 문구와 테마는 앱 맨 바깥에서 한 번만 준다
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ConfigProvider locale={koKR} theme={appTheme}>
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
)
