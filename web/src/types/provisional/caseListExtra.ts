// 임시 타입: 사건 목록 표에 더 보이는 값 (제출기일 원문 글자 · 지금 단계 · 직접 할 일 개수).
// GET /cases 명세(docs/api/README.md)에 이 칸이 없어서 따로 둔다. CaseSummary는 고치지 않는다.
// 서버 모드에서는 모두 null → 화면이 "모름"으로 보인다 (0·없음으로 보이지 않게).
// 서버가 이 칸을 주면 CaseSummary로 옮기고 이 파일은 지운다.
export type CaseStage = 'summary' | 'compare' | 'directions' | 'drafts'

export interface CaseListExtra {
  case_id: string
  // 통지서에서 읽은 글자 그대로 (날짜로 바꾸거나 계산하지 않는다)
  response_due_raw: string | null
  stage: CaseStage | null
  todo_count: number | null
}
