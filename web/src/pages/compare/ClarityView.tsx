import { Descriptions, Typography } from 'antd'
import { StatusTag } from '../../components/StatusTag'
import { EvidenceText } from '../../components/EvidenceText'
import type { ClarityReview } from '../../types/generated/ClarityReview'

// 명확성: 짚은 문구 · 청구항 위치 · 명세서 정의
export function ClarityView({ c }: { c: ClarityReview }) {
  return (
    <Descriptions size="small" column={1} bordered>
      <Descriptions.Item label="짚은 문구">
        <Typography.Text strong>'{c.term}'</Typography.Text>
      </Descriptions.Item>
      <Descriptions.Item label="청구항 위치">{c.claim_location}</Descriptions.Item>
      <Descriptions.Item label="명세서 정의">
        {c.spec_definition ? (
          <EvidenceText e={c.spec_definition} />
        ) : (
          <StatusTag status={c.status} />
        )}
      </Descriptions.Item>
      <Descriptions.Item label="참고">
        <Typography.Text type="secondary">{c.note}</Typography.Text>
      </Descriptions.Item>
      <Descriptions.Item label="상태">
        <StatusTag status={c.status} />
      </Descriptions.Item>
    </Descriptions>
  )
}
