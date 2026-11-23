import { Button, Typography } from 'antd'
import { useState } from 'react'
import { editionText, textKindText } from '../format'
import { furtherReviewWhyLabel, reviewVerdictLabel, sourceKindLabel, speakerLabel } from '../labels'
import type { LegalEvidenceBundle, LegalSource } from '../types/generated/LegalEvidenceBundle'
import { AiTag, HumanCheckTag } from './Marks'
import { StatusLine } from './StatusLine'

// 근거 한 줄: 제목 + (확인됨 아니면 꼬리표) + "자세히". 펼치면 원문 위치·원문 일부
// candidate = 추가 검토할 자료: 원문은 확인했지만 근거 검토 전이라, "확인됨" 대신 "검토 전 후보"로 보이고 위치는 늘 보인다
function SourceRow({ s, candidate = false }: { s: LegalSource; candidate?: boolean }) {
  const [open, setOpen] = useState(false)
  const confirmed = s.status.value === 'confirmed'
  const where = (
    <span className="label1 t3">
      원문 위치: {s.evidence.location ?? '—'}
      {(s.court || s.decided_on) && ` · ${[s.court, s.decided_on].filter(Boolean).join(' ')}`}
      {s.speaker && ` · ${speakerLabel[s.speaker]}`}
    </span>
  )
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: '14px 0',
        borderBottom: '1px solid var(--line-neutral-tertiary)',
      }}
    >
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="body1" style={{ flex: '1 1 280px', fontWeight: 600 }}>
          {sourceKindLabel[s.source_kind]} · {s.identifier}
          {textKindText(s) && ` · ${textKindText(s)}`}
          {/* 판본은 법령·심사기준에만 있다. 제목 줄에 바로 보인다 */}
          {editionText(s) && ` · ${editionText(s)}`}
        </span>
        {!confirmed && <StatusLine status={s.status} />}
        <Button type="text" size="small" onClick={() => setOpen(!open)}>
          {open ? '접기' : '자세히'}
        </Button>
      </div>
      {confirmed && !candidate && !open && <StatusLine status={s.status} />}
      {candidate && !open && where}
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, paddingLeft: 2 }}>
          {s.evidence.raw_text && <span className="body2r t2">“{s.evidence.raw_text}”</span>}
          {where}
          {confirmed && !candidate && <StatusLine status={s.status} />}
        </div>
      )}
    </div>
  )
}

// 법률 근거 묶음: 주장마다 제목 + 근거 줄. "적용된다"는 판단은 하지 않는다 (근거와 상태만)
export function LegalBundleView({ b }: { b: LegalEvidenceBundle }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {/* 법률 질문 답은 AI 결과임을 머리에 한 번 보인다 */}
          <AiTag>AI 답</AiTag>
          <span className="label2 t3">
            {b.question.as_of ?? '현행'} · 확인 기준일 {b.checked_on}
          </span>
          <StatusLine status={b.status} />
        </div>
      </div>
      {b.claims.map((c) => (
        <div key={c.no} style={{ display: 'flex', flexDirection: 'column' }}>
          <h2 className="headline1" style={{ marginBottom: 4 }}>
            {c.text}
          </h2>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <StatusLine status={c.status} />
            {c.flags.includes('needs_human_review') && <HumanCheckTag>직접 검토 필요</HumanCheckTag>}
          </div>
          {c.review ? (
            <span className="label1 t3" style={{ marginTop: 4 }}>
              {reviewVerdictLabel[c.review.verdict]} · {c.review.reason}
            </span>
          ) : (
            // 근거는 있는데 검토 결과가 없으면 "검토 안 함"을 드러낸다 (조용히 확인됨으로 보이지 않게)
            c.sources.length > 0 && (
              <span className="label1 t3" style={{ marginTop: 4 }}>
                검토 안 함
              </span>
            )
          )}
          {c.sources.map((s, i) => (
            <SourceRow key={`${s.identifier}-${s.evidence.chunk_id ?? i}`} s={s} />
          ))}
        </div>
      ))}
      {b.claims.length === 0 && (
        <Typography.Text type="secondary">
          {b.unit_id === null ? '고른 자료 유형에서 근거를 찾지 못했습니다.' : '이 판단 단위의 근거 주장이 없습니다.'}
        </Typography.Text>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <span className="label1 t3">추가 검토할 자료 {b.further_review.length}</span>
        {b.further_review.length === 0 ? (
          <span className="body2 t2">없음</span>
        ) : (
          <>
            {b.further_review.some((x) => x.source) && (
              <span className="label2 t3">찾은 글일 뿐 아직 근거로 검토하지 않았습니다. 원문을 직접 확인해 주세요.</span>
            )}
            {b.further_review.map((x) =>
              // 출처가 있으면 근거처럼 위치·판본을 보이고, 없으면(옛 결과 등) 조각 ID와 메모만
              x.source ? (
                <SourceRow key={x.chunk_id} s={x.source} candidate />
              ) : (
                <span key={x.chunk_id} className="body2 t2">
                  {furtherReviewWhyLabel[x.why]} · {x.chunk_id}
                  {x.note && ` — ${x.note}`}
                </span>
              ),
            )}
          </>
        )}
      </div>
    </div>
  )
}
