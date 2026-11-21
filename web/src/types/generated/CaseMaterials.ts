/* 이 파일은 npm run gen:types가 만든다 (scripts/web_schemas.py). 손으로 고치지 않는다. */

export type CaseId = string
export type DocumentId = string
export type Kind = string
export type Source = string
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
export type CitationKey = string | null
export type Documents = CaseDocument[]
export type What = string
export type DependsOnTasks = string[]
/**
 * 빠진 자료를 조회한 결과.
 */
export type LookupResult = 'lookup_failed' | 'body_missing' | 'unsupported_country'
export type AskUpload = boolean
export type CitationKey1 = string | null
export type Missing = MissingMaterial[]
export type Task = string
export type WaitingFor = string
export type HeldTasks = HeldTask[]
export type ReviewItemsCount = number
export type ReviewItems = ReviewItem[] | null
export type Kind1 =
  'unverified' | 'conflict' | 'needs_recheck' | 'needs_human_judgment' | 'needs_human_review' | 'missing_material'
export type Target = string
export type Label = string
export type Reason = string

export interface CaseMaterials {
  case_id: CaseId
  documents: Documents
  missing: Missing
  held_tasks: HeldTasks
  review_items_count: ReviewItemsCount
  review_items: ReviewItems
}
export interface CaseDocument {
  document_id: DocumentId
  kind: Kind
  source: Source
  status: Status
  text_status: Status | null
  citation_key: CitationKey
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
export interface MissingMaterial {
  what: What
  depends_on_tasks: DependsOnTasks
  lookup_result: LookupResult
  ask_upload: AskUpload
  citation_key: CitationKey1
}
export interface HeldTask {
  task: Task
  waiting_for: WaitingFor
}
/**
 * 사람이 봐야 할 것 하나. (propagation.py가 이 파일을 import하므로 정의는 여기에 둔다)
 */
export interface ReviewItem {
  kind: Kind1
  target: Target
  label: Label
  reason: Reason
}
