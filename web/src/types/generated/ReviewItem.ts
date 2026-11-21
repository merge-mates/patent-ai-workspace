/* 이 파일은 npm run gen:types가 만든다 (scripts/web_schemas.py). 손으로 고치지 않는다. */

export type Kind =
  'unverified' | 'conflict' | 'needs_recheck' | 'needs_human_judgment' | 'needs_human_review' | 'missing_material'
export type Target = string
export type Label = string
export type Reason = string

/**
 * 사람이 봐야 할 것 하나. (propagation.py가 이 파일을 import하므로 정의는 여기에 둔다)
 */
export interface ReviewItem {
  kind: Kind
  target: Target
  label: Label
  reason: Reason
}
