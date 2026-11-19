import { Space, Typography } from 'antd'
import type { ReactNode } from 'react'
import { SourceLink } from './SourceLink'
import { StatusTag } from './StatusTag'
import type { Status } from '../types/generated/OAResult'

// 뽑은 값 하나의 공통 칸 (ExtractedValue 모양)
interface Extracted {
  raw_text: string | null
  page: number | null
  status: Status
  candidates: { value: unknown; raw_text: string | null; page: number | null; source: 'rule' | 'model' }[]
}

const sourceName = { rule: '규칙', model: '모델' }

// 값 + (확인됨이 아니면) 상태 꼬리표 + 원문 쪽 링크.
// 확인됨은 판 머리 상태로 충분해서 칸마다 붙이지 않는다 (화면이 꼬리표로 덮이지 않게)
export function FieldValue({ v, children }: { v: Extracted; children: ReactNode }) {
  const status = v.status.value
  return (
    <Space direction="vertical" size={2}>
      <Space size={6} wrap>
        <span>{children}</span>
        {status !== 'confirmed' && <StatusTag status={v.status} />}
        <SourceLink page={v.page} rawText={v.raw_text} />
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
