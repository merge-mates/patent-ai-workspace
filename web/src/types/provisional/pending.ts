// 임시 타입: 결과 스키마 v0(#164) 범위 밖. 각 이슈에서 뽑은 타입으로 바꾼다.
// - CaseCheck·DraftCheck: 사건 전체 검사·초안 검사 (초안 검사 #40)
// - DraftPatch·LegalQuestion: 요청 스키마 (#56·#57)
// 결과 본문(②~⑤)은 types/generated/ 의 뽑은 타입을 쓴다.
import type { Drafts, OpinionKey } from '../generated/Drafts'
import type { LegalSourceKind } from '../generated/LegalEvidenceBundle'

// 사건 전체 검사
export interface CaseCheck {
  items: { name: string; result: 'ok' | 'warn' | 'fail'; detail: string }[]
  unsupported_rejections: number[] // AI가 다루지 않은 거절이유 번호
}

export interface DraftCheck {
  // 누락 검사: 거절이유 × 대상 청구항마다 의견서에서 다뤘는지
  coverage: { rejection: number; claim: number; covered: boolean; where: string | null }[]
  // 번호 불일치: 의견서·보정서에서 청구항·인용 번호가 안 맞는 곳
  number_mismatches: { where: string; detail: string }[]
}

// 임시 합성 타입: Drafts 결과 스키마에는 check 칸이 없다 (초안 검사는 범위 밖).
// API 모양은 지금 그대로 두고 #40에서 검사 결과를 어디에 둘지 정한다.
export type DraftsWithCheck = Drafts & { check: DraftCheck }

// PATCH /drafts/{id}: 의견서 한 칸 또는 보정 청구항 하나를 사람이 고친다
export type DraftPatch =
  | { section: OpinionKey; claim?: undefined; text: string }
  | { claim: number; section?: undefined; text: string }

// 법률 질문 선택 조건 (요청 본문). 생성된 LegalQuestion(결과 안 질문 객체)과는 다르다:
// 요청에는 source·as_of_source가 없고 서버가 채운다. 요청 스키마(#56·#57)가 정해지면 바꾼다.
export interface LegalQuestion {
  text: string
  as_of: string | null
  source_kinds: LegalSourceKind[]
}
