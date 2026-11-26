// 단어 단위 비교: 두 글에서 같은 부분 / 지운 부분 / 더한 부분을 나눈다 (변경 추적 표시용)
export type DiffPart = { kind: 'same' | 'removed' | 'added'; text: string }

// 단어와 띄어쓰기를 따로 자른다 ("가 나" → ["가", " ", "나"]). 끝에 글을 덧붙여도 앞 단어가 바뀐 것으로 안 보이게
const tokens = (s: string) => s.match(/\S+|\s+/g) ?? []

// 통지서 PDF에서 읽은 청구항 글자는 줄바꿈 자리에 띄어쓰기가 끼어 있다 ("정 보를", "카메 라들에서").
// 보정 뒤 글자에는 붙어 있어서, 그대로 비교하면 고치지 않은 단어도 "지우고 더함"으로 보인다.
// 보정 전 글자에서 [한글 조각][띄어쓰기 하나][한글 조각]을 붙인 단어가 보정 뒤에 있으면 붙여서 비교한다
const HANGUL = /[가-힣]$/
const HANGUL_START = /^[가-힣]/
function joinBrokenWords(a: string[], afterWords: Set<string>): string[] {
  const out: string[] = []
  for (let k = 0; k < a.length; k++) {
    const x = a[k]
    const y = a[k + 2]
    if (a[k + 1] === ' ' && y !== undefined && HANGUL.test(x) && HANGUL_START.test(y) && afterWords.has(x + y)) {
      out.push(x + y) // 줄바꿈 띄어쓰기를 지우고 한 단어로
      k += 2
    } else out.push(x)
  }
  return out
}

export function wordDiff(before: string, after: string): DiffPart[] {
  const b = tokens(after)
  const a = joinBrokenWords(tokens(before), new Set(b.filter((t) => t.trim() !== '')))
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
