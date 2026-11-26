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
  if (s.source_kind !== 'statute' && s.source_kind !== 'guideline') return null
  return s.evidence.edition ? editionClean(s.evidence.edition) : '판본 모름'
}

// 판본 글자 앞의 내부 법령 ID("특허법_212229_20191210 ")를 떼고 시행 기간만 남긴다 (변리사에게는 ID가 뜻이 없음)
export function editionClean(edition: string): string {
  return edition.replace(/^\S+_\d+_\d+\s*/, '').trim() || edition
}

// 법률 근거의 전문/요지 글자 (없으면 null)
export function textKindText(s: LegalSource): string | null {
  return s.text_kind ? (s.text_kind === 'full' ? '전문' : '요지') : null
}

// 문장 끝에 마침표가 없으면 붙인다 (서버 글 뒤에 안내 문장을 이어 붙이려고)
export function sentence(s: string): string {
  return /[.!?요다]$/.test(s.trim()) ? s.trim() : `${s.trim()}.`
}

// 확인 시각 (서버가 준 ISO 글자 → "2026. 11. 23. 오후 3:05"). 읽을 수 없으면 받은 글자 그대로 (지어내지 않음)
export function confirmedAtText(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
}

// 찾아본 범위 글자를 변리사가 읽을 말로 바꾼다.
// 서버 글자 예: "D1 조각 105개 중 hybrid 상위 10, … (cite-idx-v5) · 두 번 찾음" → "D1 본문 일부"
// 검색 방식·색인 판 이름은 개발용이라 빼고, 어느 인용발명을 찾아봤는지만 남긴다. 모양이 다르면 그대로 둔다
export function scopeText(scope: string): string {
  const cites = [...new Set([...scope.matchAll(/\b(D\d+)\s*조각/g)].map((m) => m[1]))]
  if (cites.length > 0) return `${cites.join('·')} 본문 일부`
  return scope
}

// 청구항 위치 글자에서 개발용 꼬리를 뗀다: "[글자 543-552]"(글자 오프셋), 앞에 겹친 "청구항 N"
export function claimLocationText(claim: number | null, location: string): string {
  let cleaned = location.replace(/\s*\[글자 \d+\s*[-–]\s*\d+\]/g, '').trim()
  // 앞에 청구항 번호를 따로 붙일 때만 겹친 "청구항 N"을 뗀다
  if (claim !== null) cleaned = cleaned.replace(/^청구항\s*\d+\s*/, '').replace(/^\[(.+)\]$/, '$1').trim()
  const head = claim !== null ? `청구항 ${claim}` : ''
  return [head, cleaned].filter(Boolean).join(' · ')
}

// 명확성 문제 표현: 심사관이 통지서에서 물결표(~)로 감싸 쓴 것을 떼고 보인다 ("~상기 이미지 처리 과정~" → "상기 이미지 처리 과정")
export function termText(term: string): string {
  return term.replace(/^[\s~～]+|[\s~～]+$/g, '')
}
