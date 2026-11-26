// 심사관이 짚은 위치 표기 → 원문 문단 라벨들
// ("[0080]-[0081]" → [0080],[0081], "청구항 1-3" → 청구항 1·2·3, "(청구항 1, 6)" → 청구항 1·6).
// 모양을 모르는 표기는 문단으로 짐작하지 않아 null
export function locationLabels(raw: string): string[] | null {
  // 판단 원문 속 괄호로 감싼 위치("개시하고 있어(청구항 1, 6)")는 괄호를 벗겨 읽는다
  const loc = raw.trim().replace(/^[(（]\s*/, '').replace(/\s*[)）]$/, '')
  const para = /^\[(\d{1,4})\](?:\s*-\s*\[(\d{1,4})\])?$/.exec(loc)
  if (para) {
    const a = Number(para[1])
    const b = para[2] ? Number(para[2]) : a
    const width = para[1].length
    return Array.from({ length: Math.max(0, b - a) + 1 }, (_, i) => `[${String(a + i).padStart(width, '0')}]`)
  }
  // 인용문헌 청구항: "청구항 1-3", "청구항 1, 6", "청구항 1 및 6"
  const claim = /^청구항\s*제?\s*([\d\s,\-및]+?)\s*항?$/.exec(loc)
  if (claim) {
    const out: string[] = []
    for (const part of claim[1].split(/,|및/)) {
      const m = /^\s*(\d+)(?:\s*-\s*(\d+))?\s*$/.exec(part)
      if (!m) return null
      const a = Number(m[1])
      const b = m[2] ? Number(m[2]) : a
      for (let n = a; n <= b; n++) out.push(`청구항 ${n}`)
    }
    return out.length > 0 ? out : null
  }
  if (/^도\s*\d+/.test(loc) || loc === '요약') return [loc]
  return null
}
