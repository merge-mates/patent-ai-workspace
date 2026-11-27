// 초안 검사 결과가 실제로 들어왔을 때만 검사 화면에서 읽는다 (#40).
import type { Drafts } from '../types/generated/Drafts'
import type { DraftsWithCheck } from '../types/provisional/pending'

// check가 객체이고 두 목록(coverage·number_mismatches)이 배열이면 검사 결과가 있는 것으로 본다
export function hasDraftCheck(d: Drafts): d is DraftsWithCheck {
  const check: unknown = (d as { check?: unknown }).check
  if (typeof check !== 'object' || check === null) return false
  const c = check as { coverage?: unknown; number_mismatches?: unknown }
  return Array.isArray(c.coverage) && Array.isArray(c.number_mismatches)
}
