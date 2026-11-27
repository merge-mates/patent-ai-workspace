import type { ComparisonTable } from '../../types/generated/ComparisonTable'

// 차이점 후보 구성요소 이름.
// - 진보성: 인용발명을 결합해서 보므로, 어느 인용발명 하나에서라도 "같은 구성"으로 찾은 구성요소는 차이점이 아니다.
//   데이터의 difference_candidate는 "그 인용문헌에서 대응 기재를 못 찾음"이라, 모든 인용발명에서 못 찾은 구성요소만 센다
// - 신규성: 인용발명 하나와만 대비하므로 그 문헌에서 못 찾은 구성요소가 곧 차이점이다
// (같은 구성요소가 여러 줄이어도 한 번만)
export function differenceElements(t: ComparisonTable): string[] {
  const diff = t.rows.filter((r) => r.judgment === 'difference_candidate')
  if (t.summary.kind === 'novelty') return [...new Set(diff.map((r) => r.element))]
  const found = new Set(t.rows.filter((r) => r.judgment === 'disclosed').map((r) => r.element))
  return [...new Set(diff.filter((r) => !found.has(r.element)).map((r) => r.element))]
}
