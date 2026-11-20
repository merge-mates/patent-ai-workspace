// 임시 타입: ⑤ 대응 방향 후보 · 의견서·보정 청구항 초안 · 초안 검사 · 사건 전체 검사.
// F2~F4 설계 뒤 뽑은 타입으로 바꿈. 칸은 docs/data-model.md 4절 ⑤ 방향과 ADR 0001, 대응_방향_분류.md 3절을 따랐다.
import type { ResultCommon } from './analysis'

export type Confidence = 'high' | 'medium' | 'low' // 높음 / 중간 / 낮음 (낮음 = 직접 판단 필요)
export type CoarseDirection = 'argue_only' | 'amend_and_argue' | 'amend_only' // 반박만 / 보정+반박 / 보정만

export interface DirectionCandidate {
  candidate_id: string
  rank: number | null // 확신 낮음이면 null (순위 없음)
  coarse: CoarseDirection
  name: string // 방향 이름 한 줄
  confidence: Confidence
  reason: string // 짧은 이유 한 줄 (늘 보임)
  evidence: { text: string; location: string }[] // 자세히: 근거(원문 위치)
  checks: string[] // 자세히: 확인 사항 (권리범위가 얼마나 줄어드나 등)
  per_rejection: { rejection: number; response: string }[] // 거절이유별 대응
  amendment_core: { claim: number; kind: string; source: string | null }[] // 보정 핵심 (청구항별 종류 + 부가한 구성의 출처)
  rebuttal: { type: string; summary: string } | null // 반박 논리 유형 + 요지
}

export interface DirectionSelection {
  candidate_id: string
  origin: 'ai_default' | 'human_selected'
}

// 묶음 하나의 후보들. 확신 낮은 묶음은 selection이 null (미리 고르지 않음)
export interface DirectionCandidates extends ResultCommon {
  unit_id: string
  candidates: DirectionCandidate[]
  selection: DirectionSelection | null
}

// 사건 전체 검사
export interface CaseCheck {
  items: { name: string; result: 'ok' | 'warn' | 'fail'; detail: string }[]
  unsupported_rejections: number[] // AI가 다루지 않은 거절이유 번호
}

// 의견서 초안: 순서대로 사건 정보 → 지적 요지 → 대응과 근거 → 보정 설명 → 마무리
export interface OpinionSection {
  key: 'case_info' | 'points' | 'response' | 'amendment' | 'closing'
  title: string
  ai_text: string // AI 원문 (늘 남긴다)
  human_text: string | null // 사람이 고친 글. 안 고쳤으면 null
}

export interface AmendedClaim {
  claim: number
  unit_id: string
  before: string // OA 당시 청구항
  after: string | null // 보정 초안. 보류면 null
  human_text: string | null // 사람이 고친 보정 초안
  spec_basis: { text: string; location: string }[] // 최초 명세서 근거 위치
  held_reason: string | null // 보류 이유 (확신 낮은 묶음: 방향을 골라 주세요)
}

export interface DraftCheck {
  // 누락 검사: 거절이유 × 대상 청구항마다 의견서에서 다뤘는지
  coverage: { rejection: number; claim: number; covered: boolean; where: string | null }[]
  // 번호 불일치: 의견서·보정서에서 청구항·인용 번호가 안 맞는 곳
  number_mismatches: { where: string; detail: string }[]
}

export interface Drafts extends ResultCommon {
  draft_id: string
  // 이 초안을 만들 때 쓴 선택 (묶음마다 후보). 지금 선택과 다르면 "다시 확인 필요"
  based_on: { unit_id: string; candidate_id: string }[]
  opinion: OpinionSection[]
  claims: AmendedClaim[]
  check: DraftCheck
}

// PATCH /drafts/{id}: 의견서 한 칸 또는 보정 청구항 하나를 사람이 고친다
export type DraftPatch =
  | { section: OpinionSection['key']; claim?: undefined; text: string }
  | { claim: number; section?: undefined; text: string }
