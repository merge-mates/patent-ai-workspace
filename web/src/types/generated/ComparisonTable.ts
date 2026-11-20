/* 이 파일은 npm run gen:types가 만든다 (scripts/web_schemas.py). 손으로 고치지 않는다. */

/**
 * 상태 네 값. 이 밖의 값은 저장 전에 거부한다.
 */
export type StatusValue = 'confirmed' | 'unverified' | 'not_found_in_scope' | 'conflict'
/**
 * `unverified`일 때 왜 확인되지 않았나.
 */
export type UnverifiedReason =
  | 'lookup_failed'
  | 'body_missing'
  | 'edition_unknown'
  | 'not_extracted'
  | 'ambiguous'
  | 'input_unverified'
  | 'evidence_rejected'
  | 'limit_reached'
export type Checked = string | null
export type SearchedScope = string | null
export type DocumentId = string
export type Page = number | null
export type Location = string | null
export type RawText = string | null
export type Edition = string | null
export type CheckedOn = string | null
export type ChunkId = string | null
export type IndexVersion = string | null
export type Evidence = Evidence1[]
export type Origin = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited'
export type NeedsRecheck = boolean
export type RecheckReason = string | null
export type Flag = 'needs_human_judgment' | 'needs_human_review'
export type Flags = Flag[]
export type UnitId = string
/**
 * 거절이유 종류. 정답 형식(f1-oa-gold.md 4절 `kind`)과 같은 코드.
 */
export type RejectionKind = 'novelty' | 'inventive_step' | 'clarity' | 'other'
export type Label = string
export type Number = string
export type Compared = boolean
export type SkippedReason = string | null
export type Citations = ComparedCitation[]
export type Evidence2 = Evidence1[]
export type Origin1 = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited'
export type NeedsRecheck1 = boolean
export type RecheckReason1 = string | null
export type Flags1 = Flag[]
export type Claim = number
export type Element = string
export type ElementLocation = string
export type Citation = string
export type Judgment = 'disclosed' | 'difference_candidate' | 'unclear'
export type ParagraphSource = 'examiner' | 'ai_found'
export type WhyRetrieved = string | null
export type Rows = ComparisonRow[]
export type Summary = InventiveSummary | NoveltySummary
export type Kind = 'inventive_step'
export type Differences = string[]
export type Combination = string
export type EffectCandidates = string[]
export type Kind1 = 'novelty'
export type Citation1 = string
export type NoveltyVerdict = 'no_difference' | 'substantially_same_candidate' | 'different'
export type Reason = string

export interface ComparisonTable {
  status: Status
  evidence: Evidence
  origin: Origin
  needs_recheck: NeedsRecheck
  recheck_reason: RecheckReason
  flags: Flags
  unit_id: UnitId
  rejection_kind: RejectionKind
  citations: Citations
  rows: Rows
  summary: Summary
}
/**
 * 상태 객체. 직렬화하면 늘 네 키(없는 키는 null).
 */
export interface Status {
  value: StatusValue
  reason: UnverifiedReason | null
  checked: Checked
  searched_scope: SearchedScope
}
/**
 * 근거 위치. 화면이 그 쪽 text에서 raw_text를 찾아 강조한다.
 *
 * document_id: 원문을 여는 문서 ID. 올린 문서면 DB 문서 ID, 색인 조각이면 색인 doc_id(+ chunk_id).
 */
export interface Evidence1 {
  document_id: DocumentId
  page: Page
  location: Location
  raw_text: RawText
  edition: Edition
  checked_on: CheckedOn
  chunk_id: ChunkId
  index_version: IndexVersion
}
export interface ComparedCitation {
  label: Label
  number: Number
  compared: Compared
  skipped_reason: SkippedReason
  skipped_status: Status | null
}
export interface ComparisonRow {
  status: Status
  evidence: Evidence2
  origin: Origin1
  needs_recheck: NeedsRecheck1
  recheck_reason: RecheckReason1
  flags: Flags1
  claim: Claim
  element: Element
  element_location: ElementLocation
  citation: Citation
  judgment: Judgment
  paragraph_source: ParagraphSource
  why_retrieved: WhyRetrieved
}
/**
 * 진보성 요약: 차이점 → 결합 → 효과 후보 순.
 */
export interface InventiveSummary {
  kind: Kind
  differences: Differences
  combination: Combination
  effect_candidates: EffectCandidates
}
/**
 * 신규성 요약: 인용 하나와만.
 */
export interface NoveltySummary {
  kind: Kind1
  citation: Citation1
  verdict: NoveltyVerdict
  reason: Reason
}
