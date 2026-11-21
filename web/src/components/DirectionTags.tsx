import { UserOutlined } from '@ant-design/icons'
import { Tag } from 'antd'
import type { DirectionSelection } from '../types/generated/DirectionCandidates'

// 방향 선택 꼬리표: AI 기본값이면 보라, 사람이 고르면 검정(기본 꼬리표) "직접 고름"
export function OriginTag({ origin }: { origin: DirectionSelection['origin'] }) {
  // 사람이 손댄 값(human_*)만 "직접 고름", 나머지는 AI가 정한 기본값
  if (origin === 'human_selected' || origin === 'human_edited') return <Tag bordered={false}>직접 고름</Tag>
  return (
    <Tag color="purple" bordered={false}>
      AI 기본값
    </Tag>
  )
}

// 사람이 고친 글이 있는 곳 수: [사람이 고침 N곳]
export function HumanEditedTag({ count }: { count: number }) {
  return (
    <Tag color="#1677FF" icon={<UserOutlined />}>
      사람이 고침 {count}곳
    </Tag>
  )
}
