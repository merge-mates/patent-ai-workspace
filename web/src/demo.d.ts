// vite.config.ts의 가상 모듈: 시연용 실제 결과 파일 경로 → 읽는 함수 (시연 모드가 아니면 빈 객체)
declare module 'virtual:demo-results' {
  const files: Record<string, () => Promise<unknown>>
  export default files
}
