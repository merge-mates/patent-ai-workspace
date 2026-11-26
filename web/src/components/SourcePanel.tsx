import { Alert, Button, Segmented } from 'antd'
import { useState } from 'react'
import { PdfView } from './PdfView'
import { editionText, textKindText } from '../format'
import { sourceKindLabel, speakerLabel } from '../labels'
import type { LegalSource } from '../types/generated/LegalEvidenceBundle'
import type { PageText } from '../types/generated/PageText'
import { StatusLine } from './StatusLine'
import { StatusTag } from './StatusTag'
import type { CiteRef } from './sourceContext'
import type { CitedDocument } from '../types/provisional/citedDocument'

export interface PanelTab {
  key: string // 'oa' 또는 인용문헌 번호
  label: string
}

// 판에 연 인용문헌 원문 전체 상태: 받는 중(doc null, failed false) / 받음 / 못 받음
export interface CitedState {
  docId: string
  doc: CitedDocument | null
  failed: boolean
}

// 근거 글자를 찾으면 왼쪽 파란 선 + 옅은 파랑 바탕 (디자인 B 고친 판)
const highlightStyle = {
  boxShadow: 'inset 2px 0 0 #0066ff',
  background: '#0066ff0d',
  padding: '2px 4px 2px 10px',
  color: 'var(--fg-neutral-primary)',
  boxDecorationBreak: 'clone',
} as const

// 판에 연 근거: 법률 근거 또는 공통 근거 위치(대비 줄·후보 근거)
export type PanelEvidence =
  | { kind: 'legal'; source: LegalSource; checkedOn: string }
  | { kind: 'cite'; ref: CiteRef }

interface Props {
  open: boolean
  page: number
  highlight: string | null
  // 원문을 못 받았으면 null
  document: PageText | null
  // 판에 연 법률 근거. 있으면 통지서 쪽 대신 근거 글을 보인다
  evidence: PanelEvidence | null
  // 대비 줄을 열었을 때 그 인용문헌 원문 전체 (글자 보기에서 쓴다)
  cited?: CitedState | null
  // 판 위 탭: 의견제출통지서('oa') + 인용문헌(문헌 번호). 지금 탭과 바꾸기
  tabs?: PanelTab[]
  tab?: string
  onTab?: (key: string) => void
  // 인용문헌 PDF를 찾을 사건 출원번호 (로컬 인용문헌 폴더가 출원번호별)
  applicationNumber?: string | null
  onToggle: () => void
}

// 근거 하나의 판 안 모양: 머리(참고 원문 + 이름) → 메타 → 상태 줄 → 근거 글(강조) → 안내.
// 원문 전체를 여는 API가 아직 없어 근거가 가리키는 부분(raw_text)만 보인다
function EvidenceBody({ s, checkedOn }: { s: LegalSource; checkedOn: string }) {
  const meta = [
    sourceKindLabel[s.source_kind],
    // 판본은 법령·심사기준에만 의미가 있다. 모르면 "판본 모름"
    editionText(s),
    textKindText(s),
    // 판례·심결은 법원 판단인지 당사자 주장인지 가른다
    s.speaker ? speakerLabel[s.speaker] : null,
    [s.court, s.decided_on].filter(Boolean).join(' ') || null,
    `확인 기준일 ${s.evidence.checked_on ?? checkedOn}`,
  ].filter(Boolean)
  return (
    <>
      <span className="label2 t3">{meta.join(' · ')}</span>
      <div>
        <StatusLine status={s.status} />
      </div>
      {s.evidence.raw_text ? (
        <p
          className="body2r"
          style={{ margin: 0, color: 'var(--fg-neutral-secondary)', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}
        >
          <span id="source-highlight" style={highlightStyle}>
            {s.evidence.raw_text}
          </span>
        </p>
      ) : (
        <Alert type="info" showIcon message="이 근거의 원문 글자를 받지 못했어요" />
      )}
      {s.evidence.location && <span className="label1 t3">원문 위치: {s.evidence.location}</span>}
      <span className="label1 t3">원문 전체는 아직 열 수 없어요. 근거가 가리키는 부분만 보여요.</span>
    </>
  )
}

// 공통 근거 위치 하나(들)의 판 안 모양: 상태 → 근거 글(강조) → 위치 → 덧붙임
function CiteBody({ r }: { r: CiteRef }) {
  return (
    <>
      <div>
        <StatusLine status={r.status} unverifiedText={r.unverifiedText} />
      </div>
      {r.items.map((e, i) => (
        <div key={`${e.document_id}-${e.location}-${i}`} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {e.raw_text ? (
            <p
              className="body2r"
              style={{ margin: 0, color: 'var(--fg-neutral-secondary)', overflowWrap: 'anywhere', whiteSpace: 'pre-wrap' }}
            >
              <span id={i === 0 ? 'source-highlight' : undefined} style={highlightStyle}>
                {e.raw_text}
              </span>
            </p>
          ) : (
            <Alert type="info" showIcon message="이 근거의 원문 글자를 받지 못했어요" />
          )}
          <span className="label1 t3">
            {[e.location ? `원문 위치: ${e.location}` : null, e.page !== null ? `${e.page}쪽` : null, `문서 ${e.document_id}`, e.edition]
              .filter(Boolean)
              .join(' · ')}
          </span>
        </div>
      ))}
      {r.items.length === 0 && <Alert type="info" showIcon message="이 줄에 연결된 근거 위치가 없어요" />}
      {r.note && <span className="label1 t2">{r.note}</span>}
    </>
  )
}

// 인용문헌 원문 전체: 요약 → 청구항 → 본문 문단 → 도면 설명. 근거 문단은 강조하고 첫 근거로 판이 내려간다
function CitedFull({ cited, highlight, labels }: { cited: CitedState; highlight: Set<string>; labels: Set<string> }) {
  // 근거 조각(chunk_id)이거나 심사관이 짚은 표기(라벨)인 문단을 강조한다
  const isOn = (p: { chunk_id: string; label: string }) => highlight.has(p.chunk_id) || labels.has(p.label)
  if (cited.failed) return <Alert type="info" showIcon message={`${cited.docId} 원문을 받지 못했어요`} />
  if (!cited.doc) return <span className="label1 t3">{cited.docId} 원문을 불러오는 중이에요…</span>
  // 첫 근거 문단에만 id를 달아 판이 그리로 내려가게 한다
  const firstId = cited.doc.parts.find(isOn)?.chunk_id
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, borderTop: '1px solid var(--line-neutral-tertiary)', paddingTop: 12 }}>
      <span className="label2 t3">
        {cited.docId} 원문 전체 · {cited.doc.parts.length}개 문단 · 스크롤해서 모두 볼 수 있어요
      </span>
      {cited.doc.parts.map((p) => {
        const on = isOn(p)
        const id = p.chunk_id === firstId ? 'cited-highlight' : undefined
        return (
          <div key={p.chunk_id} id={id} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="label2" style={{ fontWeight: 600, color: on ? 'var(--fg-neutral-primary)' : 'var(--fg-neutral-tertiary)' }}>
              {p.label}
              {/* AI가 근거로 고른 문단 / 심사관이 짚은 문단을 다르게 부른다 */}
              {highlight.has(p.chunk_id) ? ' · 근거' : labels.has(p.label) ? ' · 심사관 지정' : ''}
            </span>
            <p
              className="body2r"
              style={{ margin: 0, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', color: 'var(--fg-neutral-secondary)', ...(on ? highlightStyle : {}) }}
            >
              {p.text}
            </p>
          </div>
        )
      })}
    </div>
  )
}

// 오른쪽 "참고 원문" 판. 펴면 그 쪽 글자, 접으면 48px 세로 막대.
// 단계를 옮겨도 사건 틀이 상태를 들고 있어서 접힘이 유지된다
export function SourcePanel({
  open,
  page,
  highlight,
  document,
  evidence,
  onToggle,
  cited = null,
  tabs = [],
  tab = 'oa',
  onTab = () => {},
  applicationNumber = null,
}: Props) {
  // 통지서 보기: 원본 PDF(기본) / 뽑은 글자. PDF를 못 그리면 글자 보기로 돌아간다
  const [view, setView] = useState<'pdf' | 'text'>('pdf')
  const [pdfFailed, setPdfFailed] = useState(false)
  // PDF를 못 그린 인용문헌 (그 문헌은 글자 보기로)
  const [citeFailed, setCiteFailed] = useState<string[]>([])
  const showPdf = view === 'pdf' && !pdfFailed
  if (!open) {
    return (
      <aside
        id="source-panel"
        className="source-panel source-panel-closed"
        style={{
          flex: '0 0 48px',
          background: 'var(--bg-neutral-secondary)',
          display: 'flex',
          justifyContent: 'center',
          paddingTop: 24,
        }}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-label="원문 펴기"
          style={{
            all: 'unset',
            cursor: 'pointer',
            writingMode: 'vertical-rl',
            fontSize: 14,
            lineHeight: '20px',
            fontWeight: 600,
            color: 'var(--fg-neutral-tertiary)',
            padding: '8px 4px',
          }}
        >
          원문 펴기
        </button>
      </aside>
    )
  }

  // 판에 연 법률 근거 / 지금 인용문헌 탭에 맞는 근거 줄
  const legal = evidence?.kind === 'legal' ? evidence : null
  const citeRef = evidence?.kind === 'cite' && evidence.ref.docId === tab ? evidence.ref : null
  const citeShowPdf = view === 'pdf' && !citeFailed.includes(tab) && !!applicationNumber

  // 원문은 쪽마다 끊지 않고 전체를 이어서 보인다. 강조는 가리킨 쪽(page)에서만 찾는다
  const text = document?.pages.find((p) => p.page === page)?.text ?? null
  const at = text && highlight ? text.indexOf(highlight) : -1

  return (
    <aside
      id="source-panel"
      className="source-panel"
      style={{
        flex: '1 1 440px',
        minWidth: 0,
        maxWidth: '100%',
        background: 'var(--bg-neutral-secondary)',
        padding: '24px 28px',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <div style={{ flex: '1 1 auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span className="label2 t3">참고 원문</span>
          <span className="headline2">
            {legal ? legal.source.identifier : citeRef ? citeRef.title : tab === 'oa' ? '의견제출통지서' : (tabs.find((t) => t.key === tab)?.label ?? tab)}
          </span>
        </div>
        {tab === 'oa' && !legal && document && document.status.value !== 'confirmed' && <StatusTag status={document.status} detail={false} />}
        <Button type="text" onClick={onToggle}>
          접기
        </Button>
      </div>
      {/* 무엇을 볼지: 의견제출통지서 / 인용문헌. 링크를 누르면 저절로 그 탭이 된다 */}
      {tabs.length > 1 && (
        <Segmented
          size="small"
          value={legal ? '' : tab}
          onChange={(v) => onTab(String(v))}
          options={tabs.map((t) => ({ label: t.label, value: t.key }))}
          style={{ alignSelf: 'flex-start', flexWrap: 'wrap' }}
        />
      )}
      {legal ? (
        <EvidenceBody s={legal.source} checkedOn={legal.checkedOn} />
      ) : tab !== 'oa' ? (
        // 인용문헌 탭: (누른 줄이 있으면) 근거 줄 → 원문 PDF(기본) 또는 글자(문단)
        <>
          {citeRef && <CiteBody r={citeRef} />}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="label2 t3" style={{ flex: '1 1 auto' }}>
              {tab} 원문 전체 · 스크롤해서 모두 볼 수 있어요
            </span>
            <Segmented
              size="small"
              value={citeShowPdf ? 'pdf' : 'text'}
              onChange={(v) => setView(v as 'pdf' | 'text')}
              options={[
                { label: '원본 PDF', value: 'pdf', disabled: citeFailed.includes(tab) || !applicationNumber },
                { label: '글자', value: 'text' },
              ]}
            />
          </div>
          {citeFailed.includes(tab) && <span className="label1 t3">원본 PDF를 그리지 못해 색인 문단으로 보여요</span>}
          {citeShowPdf ? (
            <PdfView
              // 문서가 바뀌면 새로 만든다: 앞 문서의 쪽 수가 남으면 없는 쪽을 그리다 화면 전체가 멈춘다
              key={`cite:${tab}`}
              url={`/api/citations/${encodeURIComponent(tab)}/file?application_number=${encodeURIComponent(applicationNumber ?? '')}`}
              page={null}
              targets={{
                texts: (citeRef?.items ?? []).map((e) => e.raw_text).filter((x): x is string => !!x),
                labels: citeRef?.highlightLabels ?? [],
              }}
              onFail={() => setCiteFailed((xs) => [...xs, tab])}
            />
          ) : cited && cited.docId === tab ? (
            <CitedFull
              cited={cited}
              highlight={new Set((citeRef?.items ?? []).map((e) => e.chunk_id).filter((x): x is string => !!x))}
              labels={new Set(citeRef?.highlightLabels ?? [])}
            />
          ) : (
            <span className="label1 t3">원문을 불러오는 중이에요…</span>
          )}
        </>
      ) : document === null ? (
        // 원문이 없어도 빈 판으로 두지 않는다
        <Alert type="info" showIcon message="원문을 받지 못했어요" />
      ) : (
        <>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="label2 t3" style={{ flex: '1 1 auto' }}>
              전체 {document.pages.length}쪽 · 스크롤해서 모두 볼 수 있어요
            </span>
            <Segmented
              size="small"
              value={showPdf ? 'pdf' : 'text'}
              onChange={(v) => setView(v as 'pdf' | 'text')}
              options={[
                { label: '원본 PDF', value: 'pdf', disabled: pdfFailed },
                { label: '글자', value: 'text' },
              ]}
            />
          </div>
          {pdfFailed && <span className="label1 t3">원본 PDF를 그리지 못해 뽑은 글자로 보여요</span>}
          {showPdf ? (
            <PdfView
              key={`oa:${document.document_id}`}
              url={`/api/documents/${encodeURIComponent(document.document_id)}/file`}
              page={page}
              targets={{ texts: highlight ? [highlight] : [], labels: [] }}
              onFail={() => setPdfFailed(true)}
            />
          ) : (
          <>
          {highlight && text !== null && at < 0 && (
            <Alert type="warning" showIcon message={`근거 글자를 ${page}쪽에서 그대로 찾지 못했습니다`} description={highlight} />
          )}
          {document.pages.map((pg) => {
            // 가리킨 쪽에서만 근거 글자를 강조한다
            const mark = pg.page === page && highlight && at >= 0
            return (
              <div key={pg.page} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {/* 쪽 머리: 쪽 링크를 누르면 여기로 내려온다 */}
                <span
                  id={`source-page-${pg.page}`}
                  className="label2"
                  style={{
                    fontWeight: 600,
                    color: pg.page === page ? 'var(--fg-neutral-primary)' : 'var(--fg-neutral-tertiary)',
                    borderTop: '1px solid var(--line-neutral-tertiary)',
                    paddingTop: 8,
                  }}
                >
                  {pg.page}쪽
                </span>
                {pg.text ? (
                  <p
                    className="body2r"
                    style={{ whiteSpace: 'pre-wrap', margin: 0, color: 'var(--fg-neutral-secondary)', overflowWrap: 'anywhere' }}
                  >
                    {mark ? (
                      <>
                        {pg.text.slice(0, at)}
                        <span id="source-highlight" style={highlightStyle}>{highlight}</span>
                        {pg.text.slice(at + highlight.length)}
                      </>
                    ) : (
                      pg.text
                    )}
                  </p>
                ) : (
                  <span className="label1 t3">이 쪽의 원문 글자를 받지 못했어요</span>
                )}
              </div>
            )
          })}
          </>
          )}
        </>
      )}
    </aside>
  )
}
