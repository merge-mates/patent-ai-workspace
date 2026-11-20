// 임시 타입: 사건 목록·사건 보기·OA 보기·사건 만들기 응답.
// 서버 응답 스키마(#56·#57)가 생기면 OpenAPI에서 뽑은 타입으로 바꿈. 손으로 오래 두지 않는다.
// 결과 본문(OAResult·CaseMaterials·ReviewItem)은 types/generated/ 의 뽑은 타입을 쓴다.
import type { NoticeKind, OAResult, RejectionKind, StatusValue } from '../generated/OAResult'

// 실행 상태 (docs/api/README.md 3절 "실행")
export type RunState =
  | 'queued'
  | 'running'
  | 'waiting_for_human'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface LatestRun {
  run_id: string
  state: RunState
  current_step: string | null
}

// GET /cases 의 한 줄
export interface CaseSummary {
  case_id: string
  case_name: string
  application_number: string | null
  latest_oa: { oa_id: string; notice_kind: NoticeKind | null }
  rejection_kinds: RejectionKind[]
  run_state: RunState
  status: StatusValue
  review_items_count: number | null // 모르면 null (0건과 다름)
  last_opened_at: string
}

// GET /cases/{id}
export interface CaseDetail {
  case_id: string
  case_name: string
  oas: { oa_id: string; notice_kind: NoticeKind | null }[]
}

// GET /oas/{oa_id}
export interface OADetail {
  oa_id: string
  case_id: string
  case_name: string
  document_id: string | null
  latest_run: LatestRun
}

// GET /oas/{oa_id}/oa-result (결과 응답 스키마: 결과를 result에 그대로 담는다)
export interface OAResultResponse {
  oa_id: string
  run_id: string
  status: StatusValue
  result: OAResult
}

// POST /cases
export interface CreatedCase {
  case_id: string
  oa_id: string
  run_id: string
}
