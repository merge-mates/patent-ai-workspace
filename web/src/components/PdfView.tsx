import { useState } from 'react'
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'

// PDF.js 작업 파일(worker): 패키지에 든 것을 Vite가 같이 내보낸다
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()

// 띄어쓰기·줄바꿈을 빼고 맞춘다 (서버가 뽑은 근거 글자와 PDF.js 글자 층은 띄어쓰기가 다를 수 있다)
const squeeze = (s: string) => s.replace(/\s+/g, '')

// 그 쪽 글자 층에서 근거 문장을 찾아 형광펜 표시를 하고 그 자리로 내린다.
// 못 찾으면 쪽 머리로만 내린다. (effect 없이: 글자 층을 다 그린 뒤 PDF.js가 부르는 자리에서 한다)
function markHighlight(pageNo: number, highlight: string | null) {
  const pageEl = document.getElementById(`source-page-${pageNo}`)
  if (!pageEl) return
  document.querySelectorAll('.pdf-hl').forEach((el) => el.classList.remove('pdf-hl'))
  const target = highlight ? squeeze(highlight) : ''
  const spans = [...pageEl.querySelectorAll<HTMLSpanElement>('.react-pdf__Page__textContent span')]
  if (target) {
    // 글자 층 span들을 이어 붙인 글에서 근거 문장의 시작·끝 위치를 찾고, 그 범위에 걸친 span을 칠한다
    let joined = ''
    const starts: number[] = []
    for (const s of spans) {
      starts.push(joined.length)
      joined += squeeze(s.textContent ?? '')
    }
    const at = joined.indexOf(target)
    if (at >= 0) {
      const end = at + target.length
      const hit = spans.filter((_, i) => {
        const a = starts[i]
        const b = i + 1 < starts.length ? starts[i + 1] : joined.length
        return b > at && a < end
      })
      hit.forEach((s) => s.classList.add('pdf-hl'))
      hit[0]?.scrollIntoView({ block: 'center' })
      return
    }
  }
  pageEl.scrollIntoView({ block: 'start' })
}

// 원본 PDF를 오른쪽 판 안에 그린다 (모든 쪽을 이어서, 글자 층 포함).
// page·highlight가 바뀌면 그 쪽만 다시 그려(key) 글자 층이 다 그려진 뒤 강조한다
export function PdfView({
  url,
  page,
  highlight,
  onFail,
}: {
  url: string
  page: number
  highlight: string | null
  onFail: () => void
}) {
  const [numPages, setNumPages] = useState(0)
  const [width, setWidth] = useState(0)
  // 판 폭에 맞춰 쪽 폭을 정한다 (처음 한 번 잰다)
  const measure = (el: HTMLDivElement | null) => {
    if (el && width === 0) setWidth(Math.max(320, el.clientWidth))
  }
  return (
    <div ref={measure} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Document
        file={url}
        onLoadSuccess={({ numPages: n }) => setNumPages(n)}
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
                  key={n === page ? `${n}|${highlight ?? ''}` : n}
                  pageNumber={n}
                  width={width}
                  renderAnnotationLayer={false}
                  onRenderTextLayerSuccess={n === page ? () => markHighlight(n, highlight) : undefined}
                />
              </div>
            </div>
          ))}
      </Document>
    </div>
  )
}
