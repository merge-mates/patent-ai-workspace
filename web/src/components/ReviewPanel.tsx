import { Card, Empty, List, Space, Tag, Typography } from 'antd'
import { lookupResultLabel, unverifiedReasonLabel } from '../labels'
import type { ReviewItem } from '../types/generated/ReviewItem'
import { HumanCheckTag } from './Marks'
import { StatusLegend } from './StatusLegend'
import { StatusTag } from './StatusTag'

interface Props {
  // 목록을 못 받았으면 null (API v0에 목록 엔드포인트가 없음) → 개수만 보인다
  items: ReviewItem[] | null
  count: number
}

// 검토할 사항 종류마다 같은 꼬리표 (상태 네 가지 + 사람이 할 일)
function KindTag({ item }: { item: ReviewItem }) {
  switch (item.kind) {
    case 'unverified':
      return <StatusTag status="unverified" />
    case 'conflict':
      return <StatusTag status="conflict" />
    case 'needs_human_judgment':
      return <HumanCheckTag>직접 판단 필요</HumanCheckTag>
    case 'needs_human_review':
      return <HumanCheckTag>직접 검토 필요</HumanCheckTag>
    case 'needs_recheck':
      return <Tag color="orange">다시 확인 필요</Tag>
    case 'missing_material':
      return <Tag color="volcano">빠진 자료</Tag>
  }
}

// reason이 코드(확인 안 된 이유·빠진 자료 조회 결과)면 한국어로, 글이면 그대로
const reasonCodes: Record<string, string> = { ...unverifiedReasonLabel, ...lookupResultLabel }
function reasonText(reason: string): string {
  return reasonCodes[reason] ?? reason
}

// 오른쪽에 늘 있는 "검토할 사항 N건" 판: 사람이 봐야 할 것을 한곳에 모은다
export function ReviewPanel({ items, count }: Props) {
  const n = items ? items.length : count
  return (
    <Card size="small" title={`검토할 사항 ${n}건`} styles={{ body: { paddingTop: 4 } }}>
      {items === null ? (
        <Typography.Text type="secondary">
          목록은 서버 API에 아직 없습니다 (개수만 보임).
        </Typography.Text>
      ) : items.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="검토할 사항 없음" />
      ) : (
        <List
          size="small"
          dataSource={items}
          renderItem={(item) => (
            <List.Item style={{ paddingInline: 0 }}>
              <Space direction="vertical" size={2}>
                <Space size={4} wrap>
                  <KindTag item={item} />
                  <Typography.Text strong>{item.label}</Typography.Text>
                </Space>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {reasonText(item.reason)}
                </Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      )}
      <StatusLegend />
    </Card>
  )
}
