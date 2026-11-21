// 화면에 보이는 글자 만들기 (값 계산은 하지 않는다. 서버가 준 값만 보기 좋게)
import type { LegalSource } from './types/generated/LegalEvidenceBundle'
import type { ExtractedValueListInt, Rejection } from './types/generated/OAResult'

// [1,2,3,4,6] → "1–4, 6"
export function claimRange(nums: number[]): string {
  if (nums.length === 0) return '없음'
  const sorted = [...nums].sort((a, b) => a - b)
  const parts: string[] = []
  let start = sorted[0]
  let prev = sorted[0]
  for (const n of [...sorted.slice(1), Number.NaN]) {
    if (n === prev + 1) {
      prev = n
      continue
    }
    parts.push(start === prev ? `${start}` : `${start}–${prev}`)
    start = n
    prev = n
  }
  return parts.join(', ')
}

// 청구항 목록 칸: 값이 있으면 "제1–4항", 없으면 원문 글자
export function claimsText(v: ExtractedValueListInt): string {
  if (v.value) return `청구항 ${claimRange(v.value)}`
  return v.raw_text ?? '—'
}

// AI가 다루지 않은 거절이유 번호: 사건 전체 검사와 정리 결과(supported=false) 양쪽에서 모은다.
// 번호가 정리 결과에 없어도 번호는 보인다
export function unsupportedRejectionNos(fromCheck: number[] | undefined, rejections: Rejection[]): number[] {
  return [...new Set([...(fromCheck ?? []), ...rejections.filter((r) => !r.supported).map((r) => r.no)])].sort((a, b) => a - b)
}

// 법률 근거의 판본 글자: 법령·심사기준만 판본이 있다. 모르면 "판본 모름" (현행으로 짐작하지 않음). 판례·심결은 null
export function editionText(s: LegalSource): string | null {
  return s.source_kind === 'statute' || s.source_kind === 'guideline' ? (s.evidence.edition ?? '판본 모름') : null
}

// 법률 근거의 전문/요지 글자 (없으면 null)
export function textKindText(s: LegalSource): string | null {
  return s.text_kind ? (s.text_kind === 'full' ? '전문' : '요지') : null
}

// 문장 끝에 마침표가 없으면 붙인다 (서버 글 뒤에 안내 문장을 이어 붙이려고)
export function sentence(s: string): string {
  return /[.!?요다]$/.test(s.trim()) ? s.trim() : `${s.trim()}.`
}
