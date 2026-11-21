import { Alert, Button } from 'antd'
import { sourceKindLabel, speakerLabel } from '../labels'
import type { LegalSource } from '../types/generated/LegalEvidenceBundle'
import type { PageText } from '../types/generated/PageText'
import { StatusTag } from './StatusTag'
import type { CiteRef } from './sourceContext'

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
  onToggle: () => void
}

// 근거 하나의 판 안 모양: 머리(참고 원문 + 이름) → 메타 → 상태 줄 → 근거 글(강조) → 안내.
// 원문 전체를 여는 API가 아직 없어 근거가 가리키는 부분(raw_text)만 보인다
function EvidenceBody({ s, checkedOn }: { s: LegalSource; checkedOn: string }) {
  const meta = [
    sourceKindLabel[s.source_kind],
    // 판본은 법령·심사기준에만 의미가 있다. 모르면 "판본 모름"
    s.source_kind === 'statute' || s.source_kind === 'guideline' ? (s.evidence.edition ?? '판본 모름') : null,
    s.text_kind ? (s.text_kind === 'full' ? '전문' : '요지') : null,
    // 판례·심결은 법원 판단인지 당사자 주장인지 가른다
    s.speaker ? speakerLabel[s.speaker] : null,
    [s.court, s.decided_on].filter(Boolean).join(' ') || null,
    `확인 기준일 ${s.evidence.checked_on ?? checkedOn}`,
  ].filter(Boolean)
  return (
    <>
      <span className="label2 t3">{meta.join(' · ')}</span>
      {s.status.value === 'confirmed' ? (
        <span className="label1" style={{ color: 'var(--fg-positive-text)' }}>
          확인됨{s.status.checked ? ` · ${s.status.checked}` : ''}
        </span>
      ) : (
        <div>
          <StatusTag status={s.status} />
        </div>
      )}
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
      {r.status.value === 'confirmed' ? (
        <span className="label1" style={{ color: 'var(--fg-positive-text)' }}>
          확인됨{r.status.checked ? ` · ${r.status.checked}` : ''}
        </span>
      ) : (
        <div>
          <StatusTag status={r.status} />
        </div>
      )}
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
      <span className="label1 t3">원문 전체는 아직 열 수 없어요. 근거가 가리키는 부분만 보여요.</span>
    </>
  )
}

// 오른쪽 "참고 원문" 판. 펴면 그 쪽 글자, 접으면 48px 세로 막대.
// 단계를 옮겨도 사건 틀이 상태를 들고 있어서 접힘이 유지된다
export function SourcePanel({ open, page, highlight, document, evidence, onToggle }: Props) {
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
          <span className="headline2">{evidence ? (evidence.kind === 'legal' ? evidence.source.identifier : evidence.ref.title) : `통지서 ${page}쪽`}</span>
        </div>
        {!evidence && document && document.status.value !== 'confirmed' && <StatusTag status={document.status} detail={false} />}
        <Button type="text" onClick={onToggle}>
          접기
        </Button>
      </div>
      {evidence ? (
        evidence.kind === 'legal' ? (
          <EvidenceBody s={evidence.source} checkedOn={evidence.checkedOn} />
        ) : (
          <CiteBody r={evidence.ref} />
        )
      ) : document === null ? (
        // 원문이 없어도 빈 판으로 두지 않는다
        <Alert type="info" showIcon message="원문을 받지 못했어요" />
      ) : (
        <>
          <span className="label2 t3">
            의견제출통지서 · 전체 {document.pages.length}쪽
          </span>
          {text === null ? (
            <Alert type="info" showIcon message="이 쪽의 원문 글자를 받지 못했습니다" />
          ) : (
            <>
              {highlight && at < 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="근거 글자를 이 쪽에서 그대로 찾지 못했습니다"
                  description={highlight}
                />
              )}
              <p
                className="body2r"
                style={{ whiteSpace: 'pre-wrap', margin: 0, color: 'var(--fg-neutral-secondary)', overflowWrap: 'anywhere' }}
              >
                {at < 0 || !highlight ? (
                  text
                ) : (
                  <>
                    {text.slice(0, at)}
                    <span id="source-highlight" style={highlightStyle}>{highlight}</span>
                    {text.slice(at + highlight.length)}
                  </>
                )}
              </p>
            </>
          )}
        </>
      )}
    </aside>
  )
}
