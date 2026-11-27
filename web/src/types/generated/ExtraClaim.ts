/* 이 파일은 npm run gen:types가 만든다 (scripts/web_schemas.py). 손으로 고치지 않는다. */

export type Claim = number
export type Action = 'amend' | 'delete' | 'add'
export type Drafts = number[]
export type Reason = string

/**
 * 1번 안은 그대로 두지만 2·3번 안이 고친 항 (변리사가 "검토해 볼 항"으로 본다).
 *
 * 1번 안이 놓친 실제 보정 항의 대부분이 다른 안에 있었다
 * (검사 17건 16개 중 14개, 예비 39개 중 24개).
 */
export interface ExtraClaim {
  claim: Claim
  action: Action
  drafts: Drafts
  reason: Reason
}
