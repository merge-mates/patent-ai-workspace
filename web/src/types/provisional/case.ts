// 임시 타입: 사건 목록·사건 보기·OA 보기·사건 만들기 응답.
// 서버 응답 스키마(#56·#57)가 생기면 OpenAPI에서 뽑은 타입으로 바꿈. 손으로 오래 두지 않는다.
// 결과 본문(OAResult·CaseMaterials·ReviewItem)은 types/generated/ 의 뽑은 타입을 쓴다.
import type { CaseMaterials } from '../generated/CaseMaterials'
import type { DirectionSelection } from '../generated/DirectionCandidates'
import type { LegalEvidenceBundle, LegalQuestion } from '../generated/LegalEvidenceBundle'
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

// GET /runs/{id}: 실행 상태 + "지금 하는 주요 작업" 한 줄 (current_step은 자유 글이라 파싱하지 않는다)
export interface RunStatus extends LatestRun {
  oa_id: string
  // 그 OA가 지금 속한 사건. 같은 출원번호 사건에 합쳐지면 합친 사건 id (#272)
  case_id?: string | null
  // 사람 기다림의 이유. 사람을 기다릴 때만 값이 있다 (서버 core/agents/orchestrator.py WaitingFor:
  // application_number / dispatch_number). 서버 칸은 str이라 모르는 값도 올 수 있다
  waiting_for?: string | null
  // 실패한 실행의 이유 (docs/api/README.md GET /runs/{id}). 실패가 아니면 null
  error: { code: string; message: string } | null
  // 자료·도구가 없어 넘긴 단계 (docs/api/README.md GET /runs/{id}). step은 지휘 도구 이름(run_f3 등), 넘긴 것이 없으면 []
  skipped_steps?: SkippedStep[]
}

export interface SkippedStep {
  step: string
  reason: string
}

// POST /oas/{oa_id}/runs (다시 돌리기) 응답: 명세에 모양이 없음(임시). POST /cases 처럼 새 실행 ID만 있다고 가정한다.
// 화면은 이 값을 읽지 않고 다시 불러온 OA의 latest_run 으로 실행을 구독한다
export interface CreatedRun {
  run_id: string
}

// PUT /directions/{unit_id}/selection 본문 (서버 SelectionIn): 후보 id 또는 직접 쓴 방향 글, 정확히 하나
export type SelectionBody = { candidate_id: string } | { written_direction: string }

// PUT /directions/{unit_id}/selection 응답 (서버 SelectionOut). run_id는 초안만 다시 만드는 새 작은 실행이라 화면이 폴링한다
export interface SelectionResult {
  unit_id: string
  run_id: string
  selection: DirectionSelection
}

// PATCH /oas/{id} (발송번호 입력) 응답: docs/api/openapi.yaml NumberEnteredOut.
// run_id는 기다리던 그 실행이 이어 도는 같은 실행이다 (화면은 이것을 폴링에 넣는다)
export interface NumberEnteredOut {
  case_id: string
  oa_id: string
  run_id: string
}

// PUT·GET /oas/{id}/oa-result/confirmation 응답 (openapi ConfirmationOut): 정리 결과 "맞아요".
// run_id = 지금 보이는 OA 정리를 낸 실행. 확인한 적 없거나 다른 실행의 정리면 confirmed_at이 null
export interface ConfirmationOut {
  oa_id: string
  run_id: string
  confirmed_at: string | null
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
  // 같은 출원번호 사건에 합쳐진 임시 사건이면 그 사건 id (#272). 그때 oas는 빈 목록
  merged_into_case_id?: string | null
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

// POST /cases/{id}/documents: 조회하지 못한 자료 올리기 (docs/api/README.md 3절, #16 T7).
// result = 고친 사건 자료 (결과 스키마 ⑥ 그대로). 화면은 올린 뒤 loader를 다시 불러 목록을 새로 받는다
export interface UploadedDocument {
  case_id: string
  document_id: string // 올린 자료의 문서 ID
  result: CaseMaterials
}

// 법률 질문 답(화면용): 이어 묻기가 되도록 대화 ID(chat_id)와 같이 돌려준다
export interface LegalAnswer {
  chat_id: string
  answer: LegalEvidenceBundle
  scope_changed: boolean // 앞 질문과 시점·자료 유형이 바뀌었는가 (서버가 알려 줌)
}

// POST /legal-chats/{id}/messages 응답: 묶음은 result에 담긴다 (docs/api/README.md)
export interface LegalChatAnswerResponse {
  chat_id: string
  no: number
  scope_changed: boolean // 앞 질문과 시점 또는 자료 유형이 달라졌는가
  result: LegalEvidenceBundle
}

// GET /legal-chats/{id}: 대화 보기
export interface LegalChatView {
  chat_id: string
  case_id: string | null
  created_at: string
  turns: {
    no: number
    question: LegalQuestion
    scope_changed: boolean
    created_at: string
    result: LegalEvidenceBundle
  }[]
  prior_evidence: string[] // 앞 턴에서 확인된 색인 조각 ID
}
