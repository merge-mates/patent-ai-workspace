/* 이 파일은 npm run gen:types가 만든다 (scripts/web_schemas.py). 손으로 고치지 않는다. */

export type DocumentId = string
export type Page1 = number
export type Text = string
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
export type Tables = string[][][]
export type Pages = Page[]

/**
 * 문서 한 건의 쪽별 글자와 문서 전체 status.
 */
export interface PageText {
  document_id: DocumentId
  pages: Pages
  status: Status
}
/**
 * 쪽 하나의 글자와 표. 쪽 번호는 1부터. status는 그 쪽에 글자가 있는지.
 */
export interface Page {
  page: Page1
  text: Text
  status: Status
  tables: Tables
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
