// 심사관이 짚은 위치 표기 → 원문 문단 라벨들 ("[0080]-[0081]" → [0080],[0081], "청구항 1-3" → 청구항 1·2·3).
// 모양을 모르는 표기("(청구항 1, 6)" 등)는 문단으로 짐작하지 않아 null
export function locationLabels(loc: string): string[] | null {
  const para = /^\[(\d{1,4})\](?:\s*-\s*\[(\d{1,4})\])?$/.exec(loc)
  if (para) {
    const a = Number(para[1])
    const b = para[2] ? Number(para[2]) : a
    const width = para[1].length
    return Array.from({ length: Math.max(0, b - a) + 1 }, (_, i) => `[${String(a + i).padStart(width, '0')}]`)
  }
  const claim = /^청구항\s*(\d+)(?:\s*-\s*(\d+))?$/.exec(loc)
  if (claim) {
    const a = Number(claim[1])
    const b = claim[2] ? Number(claim[2]) : a
    return Array.from({ length: Math.max(0, b - a) + 1 }, (_, i) => `청구항 ${a + i}`)
  }
  if (/^도\s*\d+/.test(loc) || loc === '요약') return [loc.trim()]
  return null
}
