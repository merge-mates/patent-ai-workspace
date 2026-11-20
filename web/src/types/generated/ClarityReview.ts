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
export type Claim = number
export type Term = string
export type ClaimLocation = string
export type Note = string

/**
 * 명확성 문구 검토: 청구항 하나에서 짚은 문구와 최초 명세서의 정의.
 */
export interface ClarityReview {
  status: Status
  evidence: Evidence
  origin: Origin
  needs_recheck: NeedsRecheck
  recheck_reason: RecheckReason
  flags: Flags
  unit_id: UnitId
  claim: Claim
  term: Term
  claim_location: ClaimLocation
  spec_definition: Evidence1 | null
  note: Note
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
