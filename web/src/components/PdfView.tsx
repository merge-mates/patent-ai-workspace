import { useRef, useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'

// PDF.js 작업 파일(worker): 패키지에 든 것을 Vite가 같이 내보낸다
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

// 띄어쓰기·줄바꿈을 빼고 맞춘다 (서버가 뽑은 근거 글자와 PDF.js 글자 층은 띄어쓰기가 다를 수 있다)
const squeeze = (s: string) => s.replace(/\s+/g, '')

// 문단 번호 라벨("[0032]", "청구항 3") → PDF에 찍힌 꼴 후보 (공보는 【0032】·【청구항 3】로 찍힌다)
function labelForms(label: string): string[] {
  const para = /^\[(\d+)\]$/.exec(label)
  if (para) return [`【${para[1]}】`, `[${para[1]}]`]
  const claim = /^청구항\s*(\d+)$/.exec(label)
  if (claim) return [`【청구항${claim[1]}】`, `청구항${claim[1]}`]
  return [squeeze(label)]
}
// 문단 번호 강조는 다음 문단 번호 앞까지 (너무 길면 600자에서 끊는다)
const NEXT_MARK = /【[^】]{1,8}】|\[\d{4}\]/g

// 강조할 것: 근거 문장(texts)과 문단 번호(labels). 둘 다 비면 강조 없이 쪽으로만 간다
export interface PdfTargets {
  texts: string[]
  labels: string[]
}

// 그 쪽 글자 층에서 대상을 찾아 형광펜 표시를 하고 그 자리로 내린다. 찾으면 true
function markIn(pageNo: number, targets: PdfTargets): boolean {
  const pageEl = document.getElementById(`source-page-${pageNo}`)
  if (!pageEl) return false
  const spans = [...pageEl.querySelectorAll<HTMLSpanElement>('.react-pdf__Page__textContent span')]
  // 글자 층 span들을 이어 붙인 글 (띄어쓰기 없이)과 span마다 시작 위치
  let joined = ''
  const starts: number[] = []
  for (const s of spans) {
    starts.push(joined.length)
    joined += squeeze(s.textContent ?? '')
  }
  const paint = (at: number, end: number) => {
    const hit = spans.filter((_, i) => {
      const a = starts[i]
      const b = i + 1 < starts.length ? starts[i + 1] : joined.length
      return b > at && a < end
    })
    hit.forEach((s) => s.classList.add('pdf-hl'))
    hit[0]?.scrollIntoView({ block: 'center' })
    return hit.length > 0
  }
  // 1) 근거 문장: 통째로, 안 되면 앞 40글자로 찾는다 (문단이 길면 줄바꿈·쪽 넘김으로 끊길 수 있다)
  for (const t of targets.texts) {
    const q = squeeze(t)
    if (!q) continue
    let at = joined.indexOf(q)
    let len = q.length
    if (at < 0 && q.length > 40) {
      at = joined.indexOf(q.slice(0, 40))
      len = Math.min(q.length, joined.length - at)
    }
    if (at >= 0 && paint(at, at + len)) return true
  }
  // 2) 문단 번호: 그 번호 표시부터 다음 문단 번호 앞까지
  for (const label of targets.labels) {
    for (const form of labelForms(label)) {
      const at = joined.indexOf(form)
      if (at < 0) continue
      NEXT_MARK.lastIndex = at + form.length
      const next = NEXT_MARK.exec(joined)
      const end = Math.min(next ? next.index : joined.length, at + 600)
      if (paint(at, end)) return true
    }
  }
  return false
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
  // 이번 대상으로 이미 찾았는지 (쪽 여러 개가 차례로 그려지므로 처음 찾은 곳에서 멈춘다)
  const found = useRef<{ sig: string; done: boolean }>({ sig: '', done: false })
  const measure = (el: HTMLDivElement | null) => {
    if (el && width === 0) setWidth(Math.max(320, el.clientWidth))
  }
  const onTextLayer = (n: number) => {
    if (found.current.sig !== sig) {
      document.querySelectorAll('.pdf-hl').forEach((el) => el.classList.remove('pdf-hl'))
      found.current = { sig, done: false }
    }
    if (found.current.done) return
    const hasTarget = targets.texts.length > 0 || targets.labels.length > 0
    if (hasTarget && markIn(n, targets)) {
      found.current.done = true
      return
    }
    // 쪽을 알면(통지서 링크) 그 쪽 머리로 간다
    if (page === n) {
      found.current.done = true
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
