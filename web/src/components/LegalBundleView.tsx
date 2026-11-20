import { Button, Tag, Typography } from 'antd'
import { useState } from 'react'
import { furtherReviewWhyLabel, reviewVerdictLabel, sourceKindLabel, speakerLabel } from '../labels'
import type { LegalEvidenceBundle, LegalSource } from '../types/generated/LegalEvidenceBundle'
import type { Status } from '../types/generated/OAResult'
import { HumanCheckTag } from './Marks'
import { StatusTag } from './StatusTag'

// 상태 글자: 확인됨은 꼬리표 없이 초록 글자("확인됨 · 무엇을 확인했나"), 나머지(확인되지 않음·충돌 등)만 꼬리표
function StatusText({ status }: { status: Status }) {
  if (status.value === 'confirmed') {
    return (
      <span className="label1" style={{ color: 'var(--fg-positive-text)' }}>
        확인됨{status.checked ? ` · ${status.checked}` : ''}
      </span>
    )
  }
  return <StatusTag status={status} />
}

// 근거 한 줄: 제목 + (확인됨 아니면 꼬리표) + "자세히". 펼치면 원문 위치·원문 일부
function SourceRow({ s }: { s: LegalSource }) {
  const [open, setOpen] = useState(false)
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
          {s.text_kind && ` · ${s.text_kind === 'full' ? '전문' : '요지'}`}
          {/* 판본은 법령·심사기준에만 있다. 제목 줄에 바로 보인다 */}
          {(s.source_kind === 'statute' || s.source_kind === 'guideline') && ` · ${s.evidence.edition ?? '판본 모름'}`}
        </span>
        {s.status.value !== 'confirmed' && <StatusText status={s.status} />}
        <Button type="text" size="small" onClick={() => setOpen(!open)}>
          {open ? '접기' : '자세히'}
        </Button>
      </div>
      {s.status.value === 'confirmed' && !open && <StatusText status={s.status} />}
      {open && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, paddingLeft: 2 }}>
          {s.evidence.raw_text && <span className="body2r t2">“{s.evidence.raw_text}”</span>}
          <span className="label1 t3">
            원문 위치: {s.evidence.location ?? '—'}
            {(s.court || s.decided_on) && ` · ${[s.court, s.decided_on].filter(Boolean).join(' ')}`}
            {s.speaker && ` · ${speakerLabel[s.speaker]}`}
          </span>
          {s.status.value === 'confirmed' && <StatusText status={s.status} />}
        </div>
      )}
    </div>
  )
}

// 법률 근거 묶음: 주장마다 제목 + 근거 줄. "적용된다"는 판단은 하지 않는다 (근거와 상태만)
// showQuestion: 질문 글을 보일지 (질문 화면은 말풍선이 따로 있어 끔, 서랍은 켬)
// showAiMark: 머리의 "AI 답" 꼬리표 (서랍처럼 바깥 머리에 "AI 결과"가 있으면 끔)
export function LegalBundleView({
  b,
  showQuestion = false,
  showAiMark = true,
}: {
  b: LegalEvidenceBundle
  showQuestion?: boolean
  showAiMark?: boolean
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {showQuestion && <span className="body1" style={{ fontWeight: 600 }}>질문: {b.question.text}</span>}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {/* 법률 질문 답은 AI 결과임을 머리에 한 번 보인다 */}
          {showAiMark && (
            <Tag color="purple" bordered={false} style={{ marginInlineEnd: 0 }}>
              AI 답
            </Tag>
          )}
          <span className="label2 t3">
            {b.question.as_of ?? '현행'} · 확인 기준일 {b.checked_on}
          </span>
          <StatusText status={b.status} />
        </div>
      </div>
      {b.claims.map((c) => (
        <div key={c.no} style={{ display: 'flex', flexDirection: 'column' }}>
          <h2 className="headline1" style={{ marginBottom: 4 }}>
            {c.text}
          </h2>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <StatusText status={c.status} />
            {c.flags.includes('needs_human_review') && <HumanCheckTag>직접 검토 필요</HumanCheckTag>}
          </div>
          {c.review && (
            <span className="label1 t3" style={{ marginTop: 4 }}>
              {reviewVerdictLabel[c.review.verdict]} · {c.review.reason}
            </span>
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
          b.further_review.map((x) => (
            <span key={x.chunk_id} className="body2 t2">
              {furtherReviewWhyLabel[x.why]} · {x.chunk_id}
              {x.note && ` — ${x.note}`}
            </span>
          ))
        )}
      </div>
    </div>
  )
}
