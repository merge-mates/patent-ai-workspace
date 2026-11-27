import { useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'

// PDF.js 작업 파일(worker): 패키지에 든 것을 Vite가 같이 내보낸다
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

// 띄어쓰기·줄바꿈을 빼고 맞춘다 (서버가 뽑은 근거 글자와 PDF.js 글자 층은 띄어쓰기가 다를 수 있다)
const squeeze = (s: string) => s.replace(/\s+/g, '')

// 문단 번호 라벨("[0032]", "청구항 3") → PDF 글자 층(띄어쓰기 뺀 글)에서 그 표시를 찾는 꼴.
// 공보는 【0032】·【청구항 3】로 찍히기도 하고, 괄호 없이 "청구항 3"으로만 찍히기도 한다.
// "청구항 1"이 "청구항 10"의 앞부분에 걸리지 않게 뒤에 숫자가 오면 뺀다
function labelPattern(label: string): RegExp {
  const para = /^\[(\d+)\]$/.exec(label)
  if (para) return new RegExp(`【${para[1]}】|\\[${para[1]}\\]`)
  const claim = /^청구항\s*(\d+)$/.exec(label)
  if (claim) return new RegExp(`【청구항${claim[1]}】|청구항${claim[1]}(?!\\d)`)
  return new RegExp(squeeze(label).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
}
// 문단·청구항 강조는 다음 문단 번호·다음 청구항 표시 앞까지 (너무 길면 600자에서 끊는다)
const NEXT_MARK = /【[^】]{1,8}】|\[\d{4}\]|청구항\d+/g

// 강조할 것: 근거 문장(texts)과 문단 번호(labels). 둘 다 비면 강조 없이 쪽으로만 간다
export interface PdfTargets {
  texts: string[]
  labels: string[]
}

// 그 쪽 글자 층에서 대상을 찾아 형광펜 표시를 한다.
// - 근거 문장(texts)을 찾으면 text=true (그 자리로 내린다)
// - 문단 번호(labels)는 이 쪽에 있는 것을 모두 칠하고 찾은 라벨을 돌려준다 ("청구항 1, 6"이면 1과 6 둘 다)
// scroll이면 처음 칠한 곳으로 내린다
function markIn(pageNo: number, texts: string[], labels: string[], scroll: boolean): { text: boolean; labels: string[] } {
  const none = { text: false, labels: [] as string[] }
  const pageEl = document.getElementById(`source-page-${pageNo}`)
  if (!pageEl) return none
  const spans = [...pageEl.querySelectorAll<HTMLSpanElement>('.react-pdf__Page__textContent span')]
  // 글자 층 span들을 이어 붙인 글 (띄어쓰기 없이)과 span마다 시작 위치
  let joined = ''
  const starts: number[] = []
  for (const s of spans) {
    starts.push(joined.length)
    joined += squeeze(s.textContent ?? '')
  }
  let moved = !scroll
  const paint = (at: number, end: number) => {
    const hit = spans.filter((_, i) => {
      const a = starts[i]
      const b = i + 1 < starts.length ? starts[i + 1] : joined.length
      return b > at && a < end
    })
    hit.forEach((s) => s.classList.add('pdf-hl'))
    if (!moved && hit[0]) {
      hit[0].scrollIntoView({ block: 'center' })
      moved = true
    }
    return hit.length > 0
  }
  // 1) 근거 문장 통째로
  for (const t of texts) {
    const q = squeeze(t)
    const at = q ? joined.indexOf(q) : -1
    if (at >= 0 && paint(at, at + q.length)) return { text: true, labels: [] }
  }
  // 2) 문단 번호·청구항: 그 표시부터 다음 표시 앞까지. 이 쪽에 있는 라벨은 모두 칠한다
  const found: string[] = []
  for (const label of labels) {
    const m = labelPattern(label).exec(joined)
    if (!m) continue
    NEXT_MARK.lastIndex = m.index + m[0].length
    const next = NEXT_MARK.exec(joined)
    const end = Math.min(next ? next.index : joined.length, m.index + 600)
    if (paint(m.index, end)) found.push(label)
  }
  if (found.length > 0) return { text: false, labels: found }
  // 3) 문단 번호가 없고 통째로도 못 찾으면 근거 문장 앞 40글자로 (문단이 길면 줄바꿈·쪽 넘김으로 끊길 수 있다)
  if (labels.length === 0) {
    for (const t of texts) {
      const q = squeeze(t)
      if (q.length <= 40) continue
      const at = joined.indexOf(q.slice(0, 40))
      if (at >= 0 && paint(at, at + Math.min(q.length, joined.length - at))) return { text: true, labels: [] }
    }
  }
  return none
}

// 원본 PDF를 오른쪽 판 안에 그린다 (모든 쪽을 이어서, 글자 층 포함).
// page를 알면 그 쪽에서만 찾고(못 찾으면 쪽 머리로), 모르면 그린 쪽마다 찾아 처음 찾은 곳에서 멈춘다.
// 대상이 바뀌면 쪽을 다시 그려(key) 글자 층이 다 그려진 뒤 강조한다 (effect 없이 PDF.js 콜백에서)
export function PdfView({
  url,
  page,
  targets,
  onFail,
}: {
  url: string
  page: number | null
  targets: PdfTargets
  onFail: () => void
}) {
  const [numPages, setNumPages] = useState(0)
  const [width, setWidth] = useState(0)
  const sig = JSON.stringify([page, targets])
  // 이번 대상으로 찾은 상태: 끝났는지, 아직 못 찾은 라벨, 이미 그 자리로 내렸는지
  // (쪽 여러 개가 차례로 그려지므로 근거 문장은 처음 찾은 곳에서 멈추고, 라벨은 다 찾을 때까지 쪽마다 찾는다)
  const found = useRef<{ sig: string; done: boolean; left: string[]; moved: boolean }>({ sig: '', done: false, left: [], moved: false })
  const measure = (el: HTMLDivElement | null) => {
    if (el && width === 0) setWidth(Math.max(320, el.clientWidth))
  }
  const onTextLayer = (n: number) => {
    if (found.current.sig !== sig) {
      document.querySelectorAll('.pdf-hl').forEach((el) => el.classList.remove('pdf-hl'))
      found.current = { sig, done: false, left: targets.labels, moved: false }
    }
    const f = found.current
    if (f.done) return
    if (targets.texts.length > 0 || f.left.length > 0) {
      const r = markIn(n, targets.texts, f.left, !f.moved)
      if (r.text) {
        f.done = true
        return
      }
      if (r.labels.length > 0) {
        f.moved = true
        f.left = f.left.filter((l) => !r.labels.includes(l))
        if (f.left.length === 0) f.done = true
        return
      }
    }
    // 쪽을 알면(통지서 링크) 그 쪽 머리로 간다
    if (page === n && !f.moved) {
      f.done = true
      document.getElementById(`source-page-${n}`)?.scrollIntoView({ block: 'start' })
    }
  }
  const watch = (n: number) => page === null || page === n
  return (
    <div ref={measure} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Document
        file={url}
        onLoadSuccess={({ numPages: count }) => setNumPages(count)}
        onLoadError={onFail}
        onSourceError={onFail}
        loading={<span className="label1 t3">원본 PDF를 불러오는 중이에요…</span>}
        error={<span className="label1 t3">원본 PDF를 그리지 못했어요</span>}
      >
        {width > 0 &&
          Array.from({ length: numPages }, (_, i) => i + 1).map((n) => (
            <div key={n} id={`source-page-${n}`} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span className="label2" style={{ fontWeight: 600, color: n === page ? 'var(--fg-neutral-primary)' : 'var(--fg-neutral-tertiary)' }}>
                {n}쪽
              </span>
              <div style={{ boxShadow: '0 0 0 1px var(--line-neutral-tertiary)', background: '#fff' }}>
                <Page
                  key={watch(n) ? `${n}|${sig}` : n}
                  pageNumber={n}
                  width={width}
                  renderAnnotationLayer={false}
                  onRenderTextLayerSuccess={watch(n) ? () => onTextLayer(n) : undefined}
                />
              </div>
            </div>
          ))}
      </Document>
    </div>
  )
}
