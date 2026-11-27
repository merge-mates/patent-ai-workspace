import { rejectionKindLabel } from '../labels'
import type { OAResult } from '../types/generated/OAResult'
import type { ReviewItem } from '../types/generated/ReviewItem'

// 검토할 사항 한 줄을 사람이 읽을 말로: 무엇을 · 왜 · 무엇을 확인할지 · 통지서 어디서 볼지.
// 값은 정리 결과(OAResult)에 이미 있는 것만 쓴다 (지어내지 않음). 모르는 꼴이면 null (원래 줄 그대로 보임)
export interface ReviewDetail {
  title: string
  why: string
  todo: string
  page: number | null
  raw: string | null
  // 청구항 줄이면 그 청구항과 묶을 열쇠 (같은 거절이유·같은 판단 문장·같은 이유면 한 줄로 합친다)
  claim?: number | null
  groupKey?: string
}

// 청구항 줄 원문 대조에서 떨어진 검사 → (왜, 확인할 것)
const ROW_FAILED: Record<string, [string, string]> = {
  '같은 취지 대상을 못 읽음': [
    "심사관이 '위에 기재한 바와 같이'처럼 앞의 판단을 가리켰는데, 어느 거절이유·청구항을 가리키는지 AI가 읽지 못했어요.",
    '판단 문장을 읽고 어느 거절이유·청구항과 같은 이유인지 확인해 주세요.',
  ],
  '위치 글자를 정답 꼴로 못 읽음': [
    '심사관이 짚은 인용 위치 표기를 AI가 문단 번호로 읽지 못했어요.',
    '판단 문장에서 인용문헌의 어느 문단을 짚었는지 확인해 주세요.',
  ],
  '모델이 애매 표시를 붙임': [
    'AI가 이 판단 문장의 해석이 둘 이상일 수 있다고 표시했어요.',
    '판단 문장을 직접 읽고 어느 청구항·인용에 대한 판단인지 확인해 주세요.',
  ],
  '위치가 어느 인용의 것인지 모름': [
    '짚은 위치가 여러 인용문헌 중 어느 것의 위치인지 문장으로 정해지지 않았어요.',
    '그 위치가 어느 인용문헌의 문단인지 확인해 주세요.',
  ],
  '문제 표현이 판단 원문 따옴표 안에 없음': [
    'AI가 고른 문제 표현이 심사관 문장의 따옴표 안 글자와 맞지 않아요.',
    '심사관이 짚은 문제 표현을 확인해 주세요.',
  ],
}

// 인용 위치 칸의 확인 안 된 이유 → (왜, 확인할 것)
const CITE_REASON: Record<string, [string, string]> = {
  ambiguous: ['통지서의 인용 위치 표기를 AI가 확실히 읽지 못했어요.', '심사관이 짚은 문단 번호를 확인해 주세요.'],
  not_extracted: [
    '거절이유 본문에서 이 인용문헌의 위치 표기를 찾지 못했어요 (청구항별 줄에 위치가 있을 수 있어요).',
    '심사관이 이 인용문헌의 어느 문단을 짚었는지 확인해 주세요.',
  ],
}

export function reviewDetail(item: ReviewItem, r: OAResult | null): ReviewDetail | null {
  if (!r || item.kind !== 'unverified') return null
  const cite = /\.rejections\[(\d+)\]\.citations\[(\d+)\]\.cited_paragraphs$/.exec(item.target)
  if (cite) {
    const rej = r.rejections[Number(cite[1])]
    const c = rej?.citations[Number(cite[2])]
    if (!rej || !c) return null
    const [why, todo] = CITE_REASON[item.reason] ?? ['통지서의 인용 위치를 AI가 확인하지 못했어요.', '심사관이 짚은 위치를 확인해 주세요.']
    const number = c.number.value ?? c.number.raw_text ?? ''
    return {
      title: `거절이유 ${rej.no} ${rejectionKindLabel[rej.kind]} · ${c.label} ${number}의 인용 위치`,
      why,
      todo,
      // 위치 글자가 없으면 그 거절이유 원문 쪽으로
      page: c.cited_paragraphs.page ?? rej.article.page,
      raw: c.cited_paragraphs.raw_text,
    }
  }
  const rowMatch = /\.claim_rows\[(\d+)\]$/.exec(item.target)
  if (rowMatch) {
    const row = r.claim_rows[Number(rowMatch[1])]
    if (!row) return null
    const rej = r.rejections.find((x) => x.no === row.rejection)
    const [why, todo] = (row.check_failed && ROW_FAILED[row.check_failed]) ?? [
      row.check_failed ? `원문 대조에서 확인하지 못했어요 (${row.check_failed}).` : '통지서에서 이 청구항에 대한 판단을 AI가 확인하지 못했어요.',
      '판단 문장을 직접 확인해 주세요.',
    ]
    return {
      title: `청구항 ${row.claim ?? '?'} · 거절이유 ${row.rejection ?? '?'}${rej ? ` ${rejectionKindLabel[rej.kind]}` : ''}`,
      why,
      todo,
      page: row.page,
      raw: row.raw_text,
      claim: row.claim,
      groupKey: `${row.rejection}|${row.page}|${row.raw_text}|${row.check_failed}`,
    }
  }
  return null
}

// 같은 판단 문장·같은 이유로 확인 못 한 청구항 줄들을 한 줄로 합친다 ("청구항 1, 2, 7 · 거절이유 3")
export function mergeDetails<T>(rows: { item: T; detail: ReviewDetail | null }[]): { item: T; detail: ReviewDetail | null }[] {
  const out: { item: T; detail: ReviewDetail | null; claims?: number[] }[] = []
  for (const row of rows) {
    const key = row.detail?.groupKey
    const same = key ? out.find((x) => x.detail?.groupKey === key) : undefined
    if (same && same.detail && row.detail?.claim != null) {
      same.claims = [...(same.claims ?? []), row.detail.claim]
      same.detail = { ...same.detail, title: same.detail.title.replace(/^청구항 [^·]+·/, `청구항 ${same.claims.join(', ')} ·`) }
      continue
    }
    out.push({ ...row, claims: row.detail?.claim != null ? [row.detail.claim] : undefined })
  }
  return out
}

// 화면에 보이는 검토할 사항 줄 수 (같은 문장·같은 이유 청구항은 한 줄로 센다). 목록을 모르면 null
export function reviewRowCount(items: ReviewItem[] | null, r: OAResult | null): number | null {
  if (items === null) return null
  return mergeDetails(items.map((item) => ({ item, detail: reviewDetail(item, r) }))).length
}
