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
export type BundleId = string
export type UnitId = string | null
export type OaId = string | null
export type Rejection = number | null
export type Text = string
export type QuestionSource = 'oa_rejection' | 'user_question'
export type AsOf = string | null
export type AsOfSource = 'user_text' | 'user_condition' | 'oa_dispatch_date' | 'none'
/**
 * 자료 종류. 값은 #24 색인의 source_kind와 같다.
 */
export type LegalSourceKind = 'statute' | 'guideline' | 'precedent' | 'trial'
export type SourceKinds = LegalSourceKind[]
export type ArticleRefs = string[]
export type CheckedOn1 = string
export type Clarifications = string[]
export type Evidence2 = Evidence1[]
export type Origin1 = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited'
export type NeedsRecheck1 = boolean
export type RecheckReason1 = string | null
export type Flags1 = Flag[]
export type No = number
export type Text1 = string
export type Identifier = string
export type TextKind = 'full' | 'summary'
export type Speaker = 'court' | 'party' | 'unknown'
export type DecidedOn = string | null
export type Court = string | null
export type Sources = LegalSource[]
export type ReviewVerdict = 'supported' | 'partial' | 'not_supported' | 'undetermined'
export type Reason = string
export type Claims = LegalClaim[]
export type ChunkId1 = string
export type FurtherReviewWhy =
  'opposite_holding' | 'edition_unknown' | 'other_edition' | 'edition_out_of_scope' | 'not_used_candidate'
export type Note = string | null
export type FurtherReview = FurtherReview1[]
export type IndexVersion1 = string | null
export type AsOf1 = string | null
export type Queries = number
export type Hits = number
export type SkippedUnverifiedEdition = number
export type SkippedUnknownDate = number
export type SearchLog = SearchLogEntry[]

export interface LegalEvidenceBundle {
  status: Status
  evidence: Evidence
  origin: Origin
  needs_recheck: NeedsRecheck
  recheck_reason: RecheckReason
  flags: Flags
  bundle_id: BundleId
  unit_id: UnitId
  oa_id: OaId
  rejection: Rejection
  question: LegalQuestion
  checked_on: CheckedOn1
  clarifications: Clarifications
  claims: Claims
  further_review: FurtherReview
  search_log: SearchLog
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
/**
 * F2가 받은 질문 하나. oa_id·rejection은 묶음 맨 위 칸에 둔다.
 */
export interface LegalQuestion {
  text: Text
  source: QuestionSource
  as_of: AsOf
  as_of_source: AsOfSource
  source_kinds: SourceKinds
  article_refs: ArticleRefs
}
export interface LegalClaim {
  status: Status
  evidence: Evidence2
  origin: Origin1
  needs_recheck: NeedsRecheck1
  recheck_reason: RecheckReason1
  flags: Flags1
  no: No
  text: Text1
  sources: Sources
  review: Review | null
}
/**
 * 법률 근거 하나: 조문·판결·심결·심사기준 절.
 */
export interface LegalSource {
  source_kind: LegalSourceKind
  identifier: Identifier
  evidence: Evidence1
  status: Status
  text_kind: TextKind | null
  speaker: Speaker | null
  decided_on: DecidedOn
  court: Court
}
/**
 * 주장이 근거로 뒷받침되는지 검토한 결과 (AI 판정, 사람이 확인).
 */
export interface Review {
  verdict: ReviewVerdict
  reason: Reason
}
/**
 * 주장에 쓰지 않았지만 사람이 더 볼 만한 색인 조각.
 */
export interface FurtherReview1 {
  chunk_id: ChunkId1
  why: FurtherReviewWhy
  note: Note
}
/**
 * 자료 종류 하나를 어떻게 찾았나 (못 찾음 ≠ 없음을 가르는 기록).
 */
export interface SearchLogEntry {
  source_kind: LegalSourceKind
  index_version: IndexVersion1
  as_of: AsOf1
  queries: Queries
  hits: Hits
  skipped_unverified_edition: SkippedUnverifiedEdition
  skipped_unknown_date: SkippedUnknownDate
}
