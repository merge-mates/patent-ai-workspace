/* 이 파일은 npm run gen:types가 만든다 (scripts/web_schemas.py). 손으로 고치지 않는다. */

/**
 * 상태 네 값. 이 밖의 값은 저장 전에 거부한다.
 */
export type StatusValue = 'confirmed' | 'unverified' | 'not_found_in_scope' | 'conflict'
/**
 * `unverified`일 때 왜 확인되지 않았나.
 */
export type UnverifiedReason =
  'lookup_failed' | 'body_missing' | 'edition_unknown' | 'not_extracted' | 'ambiguous' | 'input_unverified'
export type Checked = string | null
export type SearchedScope = string | null
export type DocumentId = string
export type Page = number | null
export type Location = string | null
export type RawText = string | null
export type Edition = string | null
export type CheckedOn = string | null
export type Evidence = Evidence1[]
export type Origin = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited'
export type NeedsRecheck = boolean
export type RecheckReason = string | null
export type Flag = 'needs_human_judgment' | 'needs_human_review'
export type Flags = Flag[]
export type BundleId = string
export type UnitId = string | null
export type Question = string
export type AsOf = string | null
export type CheckedOn1 = string
export type Evidence2 = Evidence1[]
export type Origin1 = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited'
export type NeedsRecheck1 = boolean
export type RecheckReason1 = string | null
export type Flags1 = Flag[]
export type No = number
export type Text = string
export type LegalSourceKind = 'statute' | 'exam_guideline' | 'precedent' | 'trial_decision'
export type Identifier = string
export type TextKind = 'full' | 'summary'
export type Speaker = 'court' | 'party'
export type Sources = LegalSource[]
export type Claims = LegalClaim[]
export type FurtherReview = string[]

export interface LegalEvidenceBundle {
  status: Status
  evidence: Evidence
  origin: Origin
  needs_recheck: NeedsRecheck
  recheck_reason: RecheckReason
  flags: Flags
  bundle_id: BundleId
  unit_id: UnitId
  question: Question
  as_of: AsOf
  checked_on: CheckedOn1
  claims: Claims
  further_review: FurtherReview
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
 */
export interface Evidence1 {
  document_id: DocumentId
  page: Page
  location: Location
  raw_text: RawText
  edition: Edition
  checked_on: CheckedOn
}
export interface LegalClaim {
  status: Status
  evidence: Evidence2
  origin: Origin1
  needs_recheck: NeedsRecheck1
  recheck_reason: RecheckReason1
  flags: Flags1
  no: No
  text: Text
  sources: Sources
}
/**
 * 법률 근거 하나: 조문·판결·심결·심사기준 절.
 */
export interface LegalSource {
  source_kind: LegalSourceKind
  identifier: Identifier
  text_kind: TextKind
  speaker: Speaker | null
  evidence: Evidence1
  status: Status
}
