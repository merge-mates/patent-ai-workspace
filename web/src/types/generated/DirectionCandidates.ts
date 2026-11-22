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
export type Origin = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited' | 'human_written'
export type NeedsRecheck = boolean
export type RecheckReason = string | null
export type Flag = 'needs_human_judgment' | 'needs_human_review'
export type Flags = Flag[]
export type UnitId = string
export type Evidence2 = Evidence1[]
export type Origin1 = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited' | 'human_written'
export type NeedsRecheck1 = boolean
export type RecheckReason1 = string | null
export type Flags1 = Flag[]
export type CandidateId = string
export type Rank = number | null
export type CoarseDirection = 'argue_only' | 'amend_and_argue' | 'amend_only'
export type Name = string
export type Confidence = 'high' | 'medium' | 'low'
export type Reason = string
export type Checks = string[]
export type Rejection = number
export type Response = string
export type PerRejection = RejectionResponse[]
export type Claim = number
export type AmendmentKind = 'unchanged' | 'limit' | 'add' | 'delete' | 'correct_error' | 'clarify'
/**
 * 부가한 구성이 어디서 왔나.
 */
export type AddedSource = 'other_dependent' | 'spec' | 'other'
export type AmendmentCore = AmendmentCore1[]
/**
 * 거절이유 종류. 정답 형식(f1-oa-gold.md 4절 `kind`)과 같은 코드.
 */
export type RejectionKind = 'novelty' | 'inventive_step' | 'clarity' | 'other'
export type RebuttalType =
  | 'difference'
  | 'no_motivation'
  | 'combination_difficulty'
  | 'remarkable_effect'
  | 'hindsight'
  | 'not_substantially_same'
  | 'grace_period'
  | 'obvious_error'
  | 'clear_from_description'
  | 'other'
export type Summary = string
export type Candidates = DirectionCandidate[]
export type CandidateId1 = string | null
export type WrittenDirection = string | null
export type Origin2 = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited' | 'human_written'
export type AmendmentLimit = 'initial' | 'final'
export type RawText1 = string | null
export type Page1 = number | null
export type RawText2 = string | null
export type Page2 = number | null
export type Source = 'rule' | 'model'
export type Candidates1 = CandidateAmendmentLimit[]

export interface DirectionCandidates {
  status: Status
  evidence: Evidence
  origin: Origin
  needs_recheck: NeedsRecheck
  recheck_reason: RecheckReason
  flags: Flags
  unit_id: UnitId
  candidates: Candidates
  selection: DirectionSelection | null
  amendment_limit: ExtractedValueAmendmentLimit
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
export interface DirectionCandidate {
  status: Status
  evidence: Evidence2
  origin: Origin1
  needs_recheck: NeedsRecheck1
  recheck_reason: RecheckReason1
  flags: Flags1
  candidate_id: CandidateId
  rank: Rank
  coarse: CoarseDirection
  name: Name
  confidence: Confidence
  reason: Reason
  checks: Checks
  per_rejection: PerRejection
  amendment_core: AmendmentCore
  rebuttal: Rebuttal | null
}
export interface RejectionResponse {
  rejection: Rejection
  response: Response
}
export interface AmendmentCore1 {
  claim: Claim
  kind: AmendmentKind
  source: AddedSource | null
}
export interface Rebuttal {
  rejection_kind: RejectionKind
  type: RebuttalType
  summary: Summary
}
/**
 * 묶음에서 고른 방향. 후보 id 또는 사람이 쓴 글 중 정확히 하나.
 *
 * AI 기본값·사람 선택·사람이 직접 쓴 글을 origin으로 구분한다.
 */
export interface DirectionSelection {
  candidate_id: CandidateId1
  written_direction: WrittenDirection
  origin: Origin2
}
export interface ExtractedValueAmendmentLimit {
  value: AmendmentLimit | null
  raw_text: RawText1
  page: Page1
  status: Status
  candidates: Candidates1
}
export interface CandidateAmendmentLimit {
  value: AmendmentLimit | null
  raw_text: RawText2
  page: Page2
  source: Source
}
