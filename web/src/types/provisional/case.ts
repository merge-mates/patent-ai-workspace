// 임시 타입: 사건 목록·사건 보기·OA 보기·사건 만들기 응답.
// 서버 응답 스키마(#56·#57)가 생기면 OpenAPI에서 뽑은 타입으로 바꿈. 손으로 오래 두지 않는다.
// 결과 본문(OAResult·CaseMaterials·ReviewItem)은 types/generated/ 의 뽑은 타입을 쓴다.
import type { LegalEvidenceBundle } from '../generated/LegalEvidenceBundle'
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

// GET /runs/{id}: 실행 상태 + "지금 하는 주요 작업" 한 줄 (current_step은 자유 글이라 파싱하지 않는다)
export interface RunStatus extends LatestRun {
  oa_id: string
  // 실패한 실행의 이유 (docs/api/README.md GET /runs/{id}). 실패가 아니면 null
  error: { code: string; message: string } | null
}

// POST /oas/{oa_id}/runs (다시 돌리기) 응답: 명세에 모양이 없음(임시). POST /cases 처럼 새 실행 ID만 있다고 가정한다.
// 화면은 이 값을 읽지 않고 다시 불러온 OA의 latest_run 으로 실행을 구독한다
export interface CreatedRun {
  run_id: string
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

// POST /cases/{id}/oas: 다음 OA 올리기 (docs/api/README.md 3절)
export interface CreatedOA {
  oa_id: string
  run_id: string
}

// POST /cases/{id}/documents: 조회하지 못한 자료 올리기. 응답 모양이 명세에 없다 (임시: 서버 응답 스키마 #56·#57 전에 정함).
// 화면은 응답 안의 값을 읽지 않고 성공 여부만 쓴다.
export type UploadedDocument = Record<string, unknown>

// 법률 질문 답: 이어 묻기가 되도록 대화 ID(chat_id)와 같이 돌려준다 (임시: F2 설계 때 정함)
export interface LegalAnswer {
  chat_id: string
  answer: LegalEvidenceBundle
}

// GET /legal-chats/{id}: 대화 보기. 응답 모양이 명세에 없다 (임시: F2 설계 때 정함).
export type LegalChatView = { chat_id?: string } & Record<string, unknown>
