import { Space, Tag, Typography } from 'antd'
import { lookupResultLabel, unverifiedReasonLabel } from '../labels'
import type { ReviewItem } from '../types/generated/ReviewItem'
import { HumanCheckTag } from './Marks'
import { StatusLegend } from './StatusLegend'
import { StatusTag } from './StatusTag'

interface Props {
  // 목록을 못 받았으면 null (API v0에 목록 엔드포인트가 없음) → 개수만 보인다
  items: ReviewItem[] | null
  // 개수도 모르면 null ("0건"으로 보이지 않게)
  count: number | null
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

// 정리 단계 아래쪽 "검토할 사항 N건"을 펼쳤을 때 줄들: 사람이 봐야 할 것을 한곳에 모은다 (제목은 바깥 제목 줄이 가진다)
export function ReviewPanel({ items, count }: Props) {
  const n = items ? items.length : count
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {items === null ? (
        <Space direction="vertical" size={4}>
          <StatusTag status="unverified" />
          <Typography.Text type="secondary">
            {n === null
              ? '검토할 사항 목록과 개수를 받지 못했습니다. 정리 결과의 상태 꼬리표를 직접 보세요.'
              : '목록은 서버 API에 아직 없습니다 (개수만 보임).'}
          </Typography.Text>
        </Space>
      ) : items.length === 0 ? (
        <Typography.Text type="secondary">검토할 사항 없음</Typography.Text>
      ) : (
        items.map((item, i) => (
          <div
            key={`${item.kind}-${item.target}-${i}`}
            style={{
              display: 'flex',
              gap: 12,
              alignItems: 'center',
              flexWrap: 'wrap',
              padding: '12px 0',
              borderBottom: '1px solid var(--line-neutral-tertiary)',
            }}
          >
            <KindTag item={item} />
            <span className="body2" style={{ fontWeight: 600, flex: '1 1 200px' }}>
              {item.label}
            </span>
            <span className="label1 t3" style={{ flex: '1 1 200px' }}>
              {reasonText(item.reason)}
            </span>
          </div>
        ))
      )}
      <StatusLegend />
    </div>
  )
}
