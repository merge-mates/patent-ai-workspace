// 초안 단계 "대응 현황 · 거절이유 × 청구항" 표와 "제출 전에 고칠 곳" 줄을 만드는 순수 함수.
// 화면에 없는 값을 지어내지 않는다: 검사 결과(check.coverage)가 없는 칸은 "검사 결과 없음"으로 둔다.
import { coarseLabel, rejectionKindLabel } from '../../labels'
import type { DirectionCandidates } from '../../types/generated/DirectionCandidates'
import type { Rejection } from '../../types/generated/OAResult'
import type { DraftsWithCheck } from '../../types/provisional/pending'

// done: 대응함(검정) / pending: 남음 · 방향 안 고름 등(갈색) / manual: AI가 다루지 않아 직접 대응(빨강)
export type CellKind = 'done' | 'pending' | 'manual'
export interface Cell {
  kind: CellKind
  text: string
}
export interface CoverageModel {
  cols: { no: number; label: string }[]
  rows: { claim: number; cells: Record<number, Cell | undefined> }[]
  total: number
  done: number
}

// 묶음(unit_id)에서 지금 고른 후보
function selectedCandidate(directions: DirectionCandidates[], unitId: string | undefined) {
  if (unitId === undefined) return { known: false, cand: null }
  const g = directions.find((d) => d.unit_id === unitId)
  const cand = g?.candidates.find((c) => c.candidate_id === g.selection?.candidate_id) ?? null
  return { known: g !== undefined, cand }
}

export function buildCoverage(
  drafts: DraftsWithCheck,
  directions: DirectionCandidates[],
  rejections: Rejection[],
  unsupported: number[],
): CoverageModel {
  const cov = drafts.check.coverage
  // 열: 정리 결과의 거절이유 + 검사·사건 전체 검사에만 있는 번호
  const nos = [...new Set([...rejections.map((r) => r.no), ...cov.map((c) => c.rejection), ...unsupported])].sort((a, b) => a - b)
  const cols = nos.map((no) => {
    const r = rejections.find((x) => x.no === no)
    return { no, label: `거절이유 ${no}${r ? ` ${rejectionKindLabel[r.kind]}` : ''}` }
  })
  // 걸리는 쌍: 거절이유의 대상 청구항 + 검사에 나온 쌍
  const pairs = new Set<string>()
  for (const r of rejections) for (const c of r.claims.value ?? []) pairs.add(`${r.no}:${c}`)
  for (const c of cov) pairs.add(`${c.rejection}:${c.claim}`)
  const claims = [...new Set([...pairs].map((k) => Number(k.split(':')[1])))].sort((a, b) => a - b)

  let total = 0
  let done = 0
  const rows = claims.map((claim) => {
    const cells: Record<number, Cell | undefined> = {}
    for (const no of nos) {
      if (!pairs.has(`${no}:${claim}`)) continue
      total += 1
      if (unsupported.includes(no)) {
        cells[no] = { kind: 'manual', text: '남음 · 직접 대응' }
        continue
      }
      const hit = cov.find((c) => c.rejection === no && c.claim === claim)
      const unitId = drafts.claims.find((c) => c.claim === claim)?.unit_id
      const sel = selectedCandidate(directions, unitId)
      if (hit?.covered) {
        done += 1
        // 어떻게: 고른 방향의 큰 갈래, 모르면 검사가 적은 "다룬 곳"
        const how = sel.cand ? coarseLabel[sel.cand.coarse] : hit.where
        cells[no] = { kind: 'done', text: how ? `대응함 · ${how}` : '대응함' }
      } else if (hit) {
        cells[no] = { kind: 'pending', text: sel.known && sel.cand === null ? '남음 · 방향 안 고름' : '남음 · 초안에 안 적음' }
      } else {
        cells[no] = { kind: 'pending', text: '남음 · 검사 결과 없음' }
      }
    }
    return { claim, cells }
  })
  return { cols, rows, total, done }
}

// 제출 전에 고칠 곳 한 줄. tag: 충돌(빨강) / 누락(노랑)
export interface Fix {
  key: string
  tag: 'conflict' | 'missing'
  title: string
  sub?: string
  action?: { kind: 'source'; page: number | null; rawText: string | null } | { kind: 'pick' } | { kind: 'claims' }
}

// 화면에 있던 정보를 빠짐없이 줄로: 누락 검사·번호 불일치·AI가 다루지 않은 거절이유·사건 전체 검사 warn/fail
export function buildFixes(
  drafts: DraftsWithCheck,
  directions: DirectionCandidates[],
  rejections: Rejection[],
  unsupported: number[],
  caseItems: { name: string; result: 'ok' | 'warn' | 'fail'; detail: string }[],
): Fix[] {
  const out: Fix[] = []
  // AI가 다루지 않은 거절이유: 통지서 쪽으로 원문 보기
  for (const no of unsupported) {
    const r = rejections.find((x) => x.no === no)
    out.push({
      key: `unsup-${no}`,
      tag: 'missing',
      title: `거절이유 ${no} · AI가 다루지 않았어요. 직접 대응해 주세요`,
      action: { kind: 'source', page: r?.evidence[0]?.page ?? null, rawText: r?.evidence[0]?.raw_text ?? null },
    })
  }
  // 누락 검사: 초안에 안 적은 거절이유 × 청구항 (다루지 않은 거절이유는 위 줄로 갈음)
  for (const c of drafts.check.coverage) {
    if (c.covered || unsupported.includes(c.rejection)) continue
    const unitId = drafts.claims.find((x) => x.claim === c.claim)?.unit_id
    const sel = selectedCandidate(directions, unitId)
    const noPick = sel.known && sel.cand === null
    out.push({
      key: `cov-${c.rejection}-${c.claim}`,
      tag: 'missing',
      title: `거절이유 ${c.rejection} × 청구항 ${c.claim} · ${noPick ? '대응 방향을 안 골랐어요' : '초안에 대응을 안 적었어요'}`,
      action: noPick ? { kind: 'pick' } : undefined,
    })
  }
  // 번호 불일치: 의견서·보정서에서 번호가 안 맞음
  for (const m of drafts.check.number_mismatches) {
    out.push({
      key: `num-${m.where}-${m.detail}`,
      tag: 'conflict',
      title: `번호 불일치 · ${m.where}`,
      sub: m.detail,
      action: { kind: 'claims' },
    })
  }
  // 사건 전체 검사: 통과(ok) 아닌 것
  caseItems.forEach((it, i) => {
    if (it.result === 'ok') return
    out.push({
      key: `case-${i}`,
      tag: it.result === 'fail' ? 'conflict' : 'missing',
      title: it.name,
      sub: `사건 전체 검사 · ${it.detail}`,
    })
  })
  return out
}
