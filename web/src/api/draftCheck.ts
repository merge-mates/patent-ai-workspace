// 초안 검사(check) 가드 (#40 전까지)
// 서버 Drafts 결과 스키마에는 check 칸이 없다. 화면은 DraftsWithCheck(초안 + 검사)를 쓰므로,
// check가 없는 응답을 그대로 형변환하면 누락 검사 칸이 undefined로 깨진다.
// 그래서 check가 실제로 있는지 보고, 없으면 오류로 막아 오류 화면에 이유를 보인다 (조용한 실패 금지).
import type { Drafts } from '../types/generated/Drafts'
import type { DraftsWithCheck } from '../types/provisional/pending'
import { ApiError } from './errors'

// check가 객체이고 두 목록(coverage·number_mismatches)이 배열이면 검사 결과가 있는 것으로 본다
export function hasDraftCheck(d: Drafts): d is DraftsWithCheck {
  const check: unknown = (d as { check?: unknown }).check
  if (typeof check !== 'object' || check === null) return false
  const c = check as { coverage?: unknown; number_mismatches?: unknown }
  return Array.isArray(c.coverage) && Array.isArray(c.number_mismatches)
}

// 검사 결과가 없으면 ApiError(draft_check_missing)를 던진다. 있으면 좁힌 타입으로 돌려준다
export function requireDraftCheck(d: Drafts): DraftsWithCheck {
  if (!hasDraftCheck(d)) {
    throw new ApiError('draft_check_missing', '초안 검사 결과 없음: 누락 검사·번호 불일치를 보일 수 없습니다', 200)
  }
  return d
}
