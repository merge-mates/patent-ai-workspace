import { Button, Typography } from 'antd'
import { useState } from 'react'
import { candidatesText } from '../../components/extracted'
import { SourceLink } from '../../components/SourceLink'
import { StatusTag } from '../../components/StatusTag'
import type { ExaminerHints } from '../../types/generated/OAResult'

// 심사관 참고사항: 회색 바탕 줄 "심사관 참고사항 | 요지 | 원문 N쪽" (디자인 B 고친 판).
// 거절이유 제목 줄 바로 아래에 놓인다. 요지가 없는데 상태가 확인됨이면(통지서에 참고사항이 없는 것) 줄을 그리지 않는다.
// 충돌이면 "자세히"에 후보와 출처(규칙/모델)를 나란히 보인다
export function HintsCard({ h }: { h: ExaminerHints }) {
  const [open, setOpen] = useState(false)
  const note = h.amendment_note
  const text = note.value ?? note.raw_text
  if (!text && note.status.value === 'confirmed') return null
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        padding: '10px 14px',
        borderRadius: 12,
        background: 'var(--bg-neutral-secondary)',
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="label1 t3">심사관 참고사항</span>
        <span className="body2" style={{ flex: '1 1 280px' }}>
          {text ?? <Typography.Text type="secondary">통지서에서 읽지 못했어요</Typography.Text>}
        </span>
        {/* 확인됨은 꼬리표 없음, 확인되지 않음·충돌만 */}
        {note.status.value !== 'confirmed' && <StatusTag status={note.status} detail={false} />}
        <SourceLink page={note.page} rawText={note.raw_text} candidate={note.status.value !== 'confirmed'} />
        {note.candidates.length > 0 && (
          <Button type="text" size="small" onClick={() => setOpen(!open)}>
            {open ? '접기' : '자세히'}
          </Button>
        )}
      </div>
      {open && note.candidates.length > 0 && <span className="label1 t3">후보: {candidatesText(note)}</span>}
    </div>
  )
}
