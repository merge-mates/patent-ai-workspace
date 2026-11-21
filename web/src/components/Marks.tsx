import { ExclamationCircleOutlined, RobotOutlined } from '@ant-design/icons'
import { Tag, Tooltip } from 'antd'
import type { ReactNode } from 'react'

// "직접 판단 필요" / "직접 검토 필요" / "직접 확인": 사람이 해야 할 일은 늘 노란 꼬리표
export function HumanCheckTag({ children = '직접 확인' }: { children?: ReactNode }) {
  return (
    <Tag color="gold" icon={<ExclamationCircleOutlined />}>
      {children}
    </Tag>
  )
}

// AI가 만든 것은 늘 보라 꼬리표 ("AI 제안"·"AI 기본값"·"AI 초안"·"AI 답" 같은 글자만 다르다)
export function AiTag({ children }: { children: ReactNode }) {
  return (
    <Tag color="purple" bordered={false} style={{ marginInlineEnd: 0 }}>
      {children}
    </Tag>
  )
}

// 사람이 고르거나 고친 것은 검정(기본) 꼬리표 ("직접 고름"·"직접 고침")
export function HumanTag({ children }: { children: ReactNode }) {
  return (
    <Tag bordered={false} style={{ marginInlineEnd: 0 }}>
      {children}
    </Tag>
  )
}

// 정리·근거·대비 화면은 판(Card) 머리에 한 번만 "AI 결과" (칸마다 붙이지 않는다)
export function AiResultMark() {
  return (
    <Tooltip title="AI가 원문에서 뽑고 원문과 대조한 결과입니다. 사람은 이 칸을 고치지 않습니다.">
      <Tag color="purple" icon={<RobotOutlined />} bordered={false} style={{ marginInlineEnd: 0 }}>
        AI 결과
      </Tag>
    </Tooltip>
  )
}

// 단계 화면 왼쪽 위 "핵심" 한 덩어리의 머리: 글자 "핵심" + 보라 "AI 제안" 꼬리표 (판 머리 "AI 결과"를 대신한다)
export function CoreLabel() {
  return (
    <span className="label2 t3" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      핵심
      <AiTag>AI 제안</AiTag>
    </span>
  )
}
