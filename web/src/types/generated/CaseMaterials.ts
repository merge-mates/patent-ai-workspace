/* 이 파일은 npm run gen:types가 만든다 (scripts/web_schemas.py). 손으로 고치지 않는다. */

export type CaseId = string
export type DocumentId = string
export type Kind = string
export type Source = string
export type Documents = CaseDocument[]
export type What = string
export type DependsOnTasks = string[]
/**
 * 빠진 자료를 조회한 결과.
 */
export type LookupResult = 'lookup_failed' | 'body_missing' | 'unsupported_country'
export type AskUpload = boolean
export type Missing = MissingMaterial[]
export type Task = string
export type WaitingFor = string
export type HeldTasks = HeldTask[]
export type ReviewItemsCount = number

export interface CaseMaterials {
  case_id: CaseId
  documents?: Documents
  missing?: Missing
  held_tasks?: HeldTasks
  review_items_count?: ReviewItemsCount
}
export interface CaseDocument {
  document_id: DocumentId
  kind: Kind
  source: Source
}
export interface MissingMaterial {
  what: What
  depends_on_tasks?: DependsOnTasks
  lookup_result: LookupResult
  ask_upload: AskUpload
}
export interface HeldTask {
  task: Task
  waiting_for: WaitingFor
}
