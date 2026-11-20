import { Card, Descriptions, Space } from 'antd'
import { AiResultMark } from '../../components/Marks'
import { FieldValue } from '../../components/FieldValue'
import { claimRange } from '../../format'
import type { ExaminerHints } from '../../types/generated/OAResult'

// 심사관 힌트: 「특허 가능한 청구항」, 【보정에 관한 참고사항】 (칸이 없으면 "없음")
export function HintsCard({ h }: { h: ExaminerHints }) {
  const allowable = h.allowable_claims.value
  return (
    <Card
      size="small"
      title={
        <Space>
          심사관 힌트 <AiResultMark />
        </Space>
      }
    >
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="특허 가능한 청구항">
          <FieldValue v={h.allowable_claims}>
            {allowable && allowable.length > 0 ? `청구항 ${claimRange(allowable)}` : '통지서에 없음'}
          </FieldValue>
        </Descriptions.Item>
        <Descriptions.Item label="보정 참고사항">
          <FieldValue v={h.amendment_note}>{h.amendment_note.value ?? h.amendment_note.raw_text ?? '통지서에 없음'}</FieldValue>
        </Descriptions.Item>
      </Descriptions>
    </Card>
  )
}
