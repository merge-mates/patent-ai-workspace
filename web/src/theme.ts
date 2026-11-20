import { theme, type ThemeConfig } from 'antd'

// 앱 전체 테마: Ant 기본 파랑 + Pretendard + 촘촘한 간격(compact).
// ConfigProvider에 한 번만 넘긴다 (main.tsx).
export const appTheme: ThemeConfig = {
  algorithm: [theme.defaultAlgorithm, theme.compactAlgorithm],
  token: {
    colorPrimary: '#1677FF',
    fontFamily:
      "'Pretendard Variable', Pretendard, -apple-system, 'Apple SD Gothic Neo', system-ui, sans-serif",
  },
}
