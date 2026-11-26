/* 이 파일은 npm run gen:types가 만든다 (scripts/web_schemas.py). 손으로 고치지 않는다. */

export type Kind = string
export type Claim = number
export type Detail = string

export interface PlanIssue {
  kind: Kind
  claim: Claim
  detail: Detail
}
