import { Space, Typography } from 'antd'
import type { ReactNode } from 'react'
import { SourceLink } from './SourceLink'
import { StatusTag } from './StatusTag'
import type {
  ExtractedValueListInt,
  ExtractedValueListStr,
  ExtractedValueNoticeKind,
  ExtractedValueStr,
} from '../types/generated/OAResult'

// 뽑은 값 하나 (ExtractedValue). 뽑은 타입을 그대로 써서 스키마가 바뀌면 타입 검사가 잡는다
type Extracted = ExtractedValueStr | ExtractedValueNoticeKind | ExtractedValueListInt | ExtractedValueListStr

// 후보 출처 글자. 뽑은 타입의 값이 늘면 Record 타입 검사가 잡는다
const sourceName: Record<ExtractedValueStr['candidates'][number]['source'], string> = { rule: '규칙', model: '모델' }

// 값 + 칸 상태 꼬리표 + 원문 쪽 링크.
// - 확인됨은 작은 체크 아이콘만 (StatusTag compact). 꼬리표가 없는 칸이 생기지 않게 칸마다 상태를 붙인다
// - 원문 링크는 원문에서 확인된 값에만 단다 (F5). 확인되지 않음·충돌은 "후보 위치"로 글을 바꾼다
export function FieldValue({ v, children }: { v: Extracted; children: ReactNode }) {
  const status = v.status.value
  return (
    <Space direction="vertical" size={2}>
      <Space size={6} wrap>
        <span>{children}</span>
        <StatusTag status={v.status} compact />
        <SourceLink page={v.page} rawText={v.raw_text} candidate={status !== 'confirmed'} />
      </Space>
      {/* 충돌이면 두 후보를 나란히 보인다 (AI가 하나를 고르지 않음) */}
      {v.candidates.length > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          후보:{' '}
          {v.candidates
            .map((c) => `${sourceName[c.source]} "${c.raw_text ?? String(c.value)}"${c.page ? ` (${c.page}쪽)` : ''}`)
            .join(' / ')}
        </Typography.Text>
      )}
    </Space>
  )
}
