// 임시 타입: ② 판단 단위 · ③ 대비표 · 명확성 문구 검토 · ④ 법률 근거 묶음.
// F2~F4 설계 뒤 뽑은 타입으로 바꿈 (core/schemas/에 생기면 npm run gen:types로). 칸은 docs/data-model.md 4절 v0 방향을 따랐다.
import type { Evidence1 as Evidence, Flag, Origin, Status } from '../generated/OAResult'

// 모든 결과가 갖는 공통 칸 (ResultBase와 같은 이름)
export interface ResultCommon {
  status: Status
  evidence: Evidence[]
  origin: Origin
  needs_recheck: boolean // 앞 입력이 바뀌어 다시 확인해야 함 (status와 따로)
  recheck_reason: string | null
  flags: Flag[]
}

// ② 판단 단위: unit_id는 내용으로 정한다 (`oa_1:29-2:c1`)
export interface JudgmentUnit extends ResultCommon {
  unit_id: string
  rejection: number // OAResult rejections[].no
  rejection_kind: 'novelty' | 'inventive_step' | 'clarity'
  unit_kind: 'independent_group' | 'single_claim' // 독립항 묶음(진보성·신규성) / 청구항 하나(명확성)
  representative_claim: number
  claims: number[]
  read_with: number[] // 명확성: 함께 읽을 청구항
  order: number
  parent_unit_id: string | null
}

export type Judgment = 'disclosed' | 'difference_candidate' | 'unclear' // 개시됨 / 차이 후보 / 불명
export type ParagraphSource = 'examiner' | 'ai_found' // 심사관 지정 / AI가 새로 찾음

export interface ComparisonRow {
  element: string // 청구항 구성요소 문구
  element_location: string // 청구항 안 위치
  citation: string // 인용문헌 라벨 D1…
  location: string | null // 식별번호·도면 번호
  judgment: Judgment
  paragraph_source: ParagraphSource
  why_retrieved: string | null // AI가 새로 찾은 문단만
  status: Status
}

export interface ComparedCitation {
  label: string
  number: string
  compared: boolean // false면 대비 안 함 (이유는 skipped_reason, 상태는 skipped_status)
  skipped_reason: string | null
  skipped_status: Status | null
}

// 진보성 요약: 차이점 → 결합 → 효과 후보 순
export interface InventiveSummary {
  kind: 'inventive_step'
  differences: string[]
  combination: string
  effect_candidates: string[]
}

// 신규성 요약: 인용 하나와만
export interface NoveltySummary {
  kind: 'novelty'
  citation: string
  verdict: 'no_difference' | 'substantially_same_candidate' | 'different'
  reason: string
}

// ③ 대비표
export interface ComparisonTable extends ResultCommon {
  unit_id: string
  rejection_kind: 'novelty' | 'inventive_step'
  citations: ComparedCitation[]
  rows: ComparisonRow[]
  summary: InventiveSummary | NoveltySummary
}

// 명확성 문구 검토 (스키마는 F3 설계 때)
export interface ClarityReview extends ResultCommon {
  unit_id: string
  claim: number
  term: string // 짚은 문구
  claim_location: string // 청구항 안 위치
  spec_definition: { text: string; location: string } | null // 최초 명세서의 정의
  note: string
}

// ④ 법률 근거
export type LegalSourceKind = 'statute' | 'exam_guideline' | 'precedent' | 'trial_decision'

export interface LegalSource {
  source_kind: LegalSourceKind
  identifier: string // 조문·판결 번호·심결 번호·심사기준 절
  edition: string | null // 판본 (법령 시행일·심사기준 개정일). 모르면 null + 판본 미확인
  location: string // 원문 위치
  text_kind: 'full' | 'summary' // 판례 전문 / 심결례 요지
  speaker: 'court' | 'party' | null // 법원 판단 / 당사자 주장
  excerpt: string
  status: Status
}

export interface LegalClaim {
  no: number
  text: string // 주장 문장
  sources: LegalSource[]
  status: Status
}

export interface LegalEvidenceBundle extends ResultCommon {
  bundle_id: string
  unit_id: string | null // OA 흐름이면 판단 단위, 법률 질문이면 null
  question: string
  as_of: string | null // 사용자가 정한 시점. 없으면 현행
  checked_on: string // 확인 기준일
  claims: LegalClaim[]
  further_review: string[] // 추가 검토할 자료
}

// 법률 질문 선택 조건
export interface LegalQuestion {
  text: string
  as_of: string | null
  source_kinds: LegalSourceKind[]
}
