// 화면에 보이는 글자 만들기 (값 계산은 하지 않는다. 서버가 준 값만 보기 좋게)
import type { ExtractedValueListInt } from './types/generated/OAResult'

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

// "2099-02-12T09:30:00" → "2099-02-12 09:30"
export function dateTimeText(iso: string): string {
  return iso.replace('T', ' ').slice(0, 16)
}
