// 단어 단위 비교: 두 글에서 같은 부분 / 지운 부분 / 더한 부분을 나눈다 (변경 추적 표시용)
export type DiffPart = { kind: 'same' | 'removed' | 'added'; text: string }

// 띄어쓰기를 붙인 채로 자른다 ("가 나 다" → ["가 ", "나 ", "다"])
const tokens = (s: string) => s.match(/\S+\s*|\s+/g) ?? []

export function wordDiff(before: string, after: string): DiffPart[] {
  const a = tokens(before)
  const b = tokens(after)
  // 가장 긴 공통 부분(LCS) 표: lcs[i][j] = a[i:]와 b[j:]의 공통 길이
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])

  const parts: DiffPart[] = []
  const push = (kind: DiffPart['kind'], text: string) => {
    const last = parts.at(-1)
    if (last && last.kind === kind) last.text += text
    else parts.push({ kind, text })
  }
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push('same', a[i])
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) push('removed', a[i++])
    else push('added', b[j++])
  }
  while (i < a.length) push('removed', a[i++])
  while (j < b.length) push('added', b[j++])
  return parts
}
