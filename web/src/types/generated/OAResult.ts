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
export type OaId = string
export type Value = string | null
export type RawText1 = string | null
export type Page1 = number | null
export type Value1 = string | null
export type RawText2 = string | null
export type Page2 = number | null
export type Source = 'rule' | 'model'
export type Candidates = CandidateStr[]
/**
 * 통지 종류. 정답 형식(f1-oa-gold.md)과 같은 코드.
 */
export type NoticeKind = 'initial' | 'final' | 'unknown'
export type RawText3 = string | null
export type Page3 = number | null
export type RawText4 = string | null
export type Page4 = number | null
export type Source1 = 'rule' | 'model'
export type Candidates1 = CandidateNoticeKind[]
export type Value2 = number[] | null
export type RawText5 = string | null
export type Page5 = number | null
export type Value3 = number[] | null
export type RawText6 = string | null
export type Page6 = number | null
export type Source2 = 'rule' | 'model'
export type Candidates2 = CandidateListInt[]
export type Evidence2 = Evidence1[]
export type Origin1 = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited'
export type NeedsRecheck1 = boolean
export type RecheckReason1 = string | null
export type Flags1 = Flag[]
export type No = number
/**
 * 거절이유 종류. 정답 형식(f1-oa-gold.md 4절 `kind`)과 같은 코드.
 */
export type RejectionKind = 'novelty' | 'inventive_step' | 'clarity' | 'other'
export type Supported = boolean
export type Label = string
export type CountrySupported = boolean
export type Value4 = string[] | null
export type RawText7 = string | null
export type Page7 = number | null
export type Value5 = string[] | null
export type RawText8 = string | null
export type Page8 = number | null
export type Source3 = 'rule' | 'model'
export type Candidates3 = CandidateListStr[]
export type Flags2 = Flag[]
export type Citations = Citation[]
export type Rejections = Rejection[]
export type Claim = number | null
export type Rejection1 = number | null
export type Citations1 = string[]
export type SameAs = string[]
export type ClarityTerms = string[]
export type ClarityReason = string | null
export type Origin2 = 'ai_generated' | 'ai_default' | 'human_selected' | 'human_edited'
export type NoLocation = string | null
export type RawText9 = string | null
export type Page9 = number | null
export type ClaimRows = ClaimRow[]

export interface OAResult {
  status: Status
  evidence: Evidence
  origin: Origin
  needs_recheck: NeedsRecheck
  recheck_reason: RecheckReason
  flags: Flags
  oa_id: OaId
  application_number: ExtractedValueStr
  dispatch_number: ExtractedValueStr
  notice_date: ExtractedValueStr
  response_due: ExtractedValueStr
  notice_kind: ExtractedValueNoticeKind
  examined_claims: ExtractedValueListInt
  examined_claim_version: ExtractedValueStr | null
  examiner_hints: ExaminerHints
  rejections: Rejections
  claim_rows: ClaimRows
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
export interface ExtractedValueStr {
  value: Value
  raw_text: RawText1
  page: Page1
  status: Status
  candidates: Candidates
}
export interface CandidateStr {
  value: Value1
  raw_text: RawText2
  page: Page2
  source: Source
}
export interface ExtractedValueNoticeKind {
  value: NoticeKind | null
  raw_text: RawText3
  page: Page3
  status: Status
  candidates: Candidates1
}
export interface CandidateNoticeKind {
  value: NoticeKind | null
  raw_text: RawText4
  page: Page4
  source: Source1
}
export interface ExtractedValueListInt {
  value: Value2
  raw_text: RawText5
  page: Page5
  status: Status
  candidates: Candidates2
}
export interface CandidateListInt {
  value: Value3
  raw_text: RawText6
  page: Page6
  source: Source2
}
export interface ExaminerHints {
  allowable_claims: ExtractedValueListInt
  amendment_note: ExtractedValueStr
}
/**
 * 거절이유 하나. 청구항은 거절이유마다 따로 둔다 (합치지 않음).
 */
export interface Rejection {
  status: Status
  evidence: Evidence2
  origin: Origin1
  needs_recheck: NeedsRecheck1
  recheck_reason: RecheckReason1
  flags: Flags1
  no: No
  kind: RejectionKind
  article: ExtractedValueStr
  supported: Supported
  claims: ExtractedValueListInt
  citations: Citations
  examiner_reasoning: ExtractedValueStr
}
export interface Citation {
  label: Label
  number: ExtractedValueStr
  country: ExtractedValueStr
  country_supported: CountrySupported
  cited_paragraphs: ExtractedValueListStr
  flags: Flags2
}
export interface ExtractedValueListStr {
  value: Value4
  raw_text: RawText7
  page: Page7
  status: Status
  candidates: Candidates3
}
export interface CandidateListStr {
  value: Value5
  raw_text: RawText8
  page: Page8
  source: Source3
}
/**
 * 청구항 줄 하나 = 청구항 x 거절이유 (정답 형식 2.4, 채점 단위).
 *
 * 값은 원문 대조를 통과했을 때만 둔다. 대조에 떨어지면 status가 unverified이고 값은 비어 있다
 * (청구항·거절이유 번호만 어느 줄인지 알리려고 남길 수 있음).
 */
export interface ClaimRow {
  claim: Claim
  rejection: Rejection1
  citations: Citations1
  locations: Locations
  same_as: SameAs
  clarity_terms: ClarityTerms
  clarity_reason: ClarityReason
  clarity_reason_origin: Origin2 | null
  no_location: NoLocation
  raw_text: RawText9
  page: Page9
  status: Status
}
export interface Locations {
  [k: string]: string[]
}
