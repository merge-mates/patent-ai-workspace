import type { ThemeConfig } from 'antd'

// 앱 전체 테마: 몽타주 토큰 값(디자인 "B 고친 판" PMain.dc.html의 theme)을 Ant Design에 그대로 준다.
// 부품은 Ant 그대로, 색·글자·모서리 값만 바꾼다. ConfigProvider에 한 번만 넘긴다 (main.tsx).
// compact 알고리즘은 쓰지 않는다 (기본 알고리즘만).
export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#0066ff',
    colorText: '#171719',
    colorTextSecondary: '#2e2f33e0',
    colorTextTertiary: '#37383c9c',
    colorBorder: '#70737c29',
    colorBorderSecondary: '#70737c14',
    colorBgLayout: '#f7f7f8',
    colorSuccess: '#00bf40',
    colorWarning: '#ff9200',
    colorError: '#ff4242',
    colorLink: '#0066ff',
    fontFamily:
      "'Pretendard Variable', Pretendard, -apple-system, 'Apple SD Gothic Neo', system-ui, sans-serif",
    fontSize: 15,
    borderRadius: 12,
    borderRadiusLG: 16,
    borderRadiusSM: 8,
    controlHeight: 40,
    controlHeightLG: 48,
    controlHeightSM: 32,
  },
  components: {
    Table: { headerBg: '#f7f7f8', headerColor: '#37383c9c', cellPaddingBlockMD: 14, cellPaddingInlineMD: 16 },
    Tag: { defaultBg: '#70737c14' },
    Steps: { titleLineHeight: 22 },
  },
}
