import { Typography } from 'antd'
import { SourceLink } from '../../components/SourceLink'
import { StatusTag } from '../../components/StatusTag'
import type { ExaminerHints } from '../../types/generated/OAResult'

// 심사관 참고사항: 회색 바탕 줄 "심사관 참고사항 | 요지 | 통지서 N쪽" (디자인 B 고친 판).
// 특허 가능한 청구항은 거절이유 제목 줄 오른쪽에 있다. 줄이 여러 개면 줄을 여러 개 그린다.
// 요지가 없는데 상태가 확인됨이면(통지서에 참고사항이 없는 것) 줄을 그리지 않는다
export function HintsCard({ h }: { h: ExaminerHints }) {
  const note = h.amendment_note
  const text = note.value ?? note.raw_text
  if (!text && note.status.value === 'confirmed') return null
  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        alignItems: 'center',
        flexWrap: 'wrap',
        padding: '10px 14px',
        borderRadius: 12,
        background: 'var(--bg-neutral-secondary)',
      }}
    >
      <span className="label1 t3">심사관 참고사항</span>
      <span className="body2" style={{ flex: '1 1 280px' }}>
        {text ?? <Typography.Text type="secondary">통지서에서 읽지 못했어요</Typography.Text>}
      </span>
      {/* 확인됨은 꼬리표 없음, 확인되지 않음·충돌만 */}
      {note.status.value !== 'confirmed' && <StatusTag status={note.status} detail={false} />}
      <SourceLink page={note.page} rawText={note.raw_text} candidate={note.status.value !== 'confirmed'} />
    </div>
  )
}
