// 임시 타입: 사건 목록·사건 보기·OA 보기·사건 만들기 응답.
// 서버 응답 스키마(#56·#57)가 생기면 OpenAPI에서 뽑은 타입으로 바꿈. 손으로 오래 두지 않는다.
// 결과 본문(OAResult·CaseMaterials·ReviewItem)은 types/generated/ 의 뽑은 타입을 쓴다.
import type {
  ExtractedValueStr,
  NoticeKind,
  OAResult,
  RejectionKind,
  StatusValue,
} from '../generated/OAResult'

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
  updated_at: string // 가장 최근 OA를 올린 시각
}

// GET /cases/{id} 의 OA 한 줄
export interface CaseOA {
  oa_id: string
  notice_kind: NoticeKind | null
  // 심사 대상 판 (값 = 만든 보정서 접수번호, 출원 때 판은 "as_filed"). 묶기 결과 저장 전이면 null
  examined_claim_version?: ExtractedValueStr | null
}

// 사건 이력 한 줄 (#16)
export interface CaseEvent {
  kind: 'oa' | 'amendment' | 'opinion' | 'registration_decision' | 'rejection_decision' | 'other'
  doc_number: string | null
  seq: number | null // 행정 이력 순서, 자료로만 온 줄은 null
}

// 청구항 판 한 줄 (#16). 0 = 출원 때 판
export interface ClaimVersion {
  version: number
  source_kind: 'application' | 'amendment' | 'publication' | 'registration'
  source_doc_number: string | null
  document_id: string | null
}

// GET /cases/{id}
export interface CaseDetail {
  case_id: string
  case_name: string
  oas: CaseOA[]
  events?: CaseEvent[] // 묶기 결과 저장 전이면 빈 목록 (선택 칸: 하위 호환)
  claim_versions?: ClaimVersion[]
}

// GET /oas/{oa_id}
export interface OADetail {
  oa_id: string
  case_id: string
  case_name: string
  document_id: string | null
  latest_run: LatestRun | null // 실행 줄이 아직 없으면 null
  dispatch_number?: string | null // 발송번호, 모르면 null (선택 칸: 하위 호환)
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
