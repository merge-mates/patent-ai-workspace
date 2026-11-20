import { RobotOutlined, UserOutlined } from '@ant-design/icons'
import { Tag } from 'antd'
import type { Confidence, DirectionSelection } from '../types/provisional/direction'
import { HumanCheckTag } from './Marks'

// 사람이 손대는 곳의 표시: [AI 기본값] 점선 꼬리표 / [사람이 고름] 파란 채운 꼬리표
export function OriginTag({ origin }: { origin: DirectionSelection['origin'] }) {
  if (origin === 'human_selected') {
    return (
      <Tag color="#1677FF" icon={<UserOutlined />}>
        사람이 고름
      </Tag>
    )
  }
  return (
    <Tag icon={<RobotOutlined />} style={{ background: '#fff', borderStyle: 'dashed' }}>
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

// 확신도 3단계 (% 숫자 안 씀). 낮음은 노란 "직접 판단 필요"
export function ConfidenceTag({ c }: { c: Confidence }) {
  if (c === 'low') return <HumanCheckTag>확신 낮음 · 직접 판단 필요</HumanCheckTag>
  return <Tag color={c === 'high' ? 'green' : 'default'}>확신 {c === 'high' ? '높음' : '중간'}</Tag>
}
