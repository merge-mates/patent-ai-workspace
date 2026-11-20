import { ExclamationCircleOutlined, ExperimentOutlined, RobotOutlined } from '@ant-design/icons'
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

// 정리·근거·대비 화면은 판(Card) 머리에 한 번만 "AI 결과" (칸마다 붙이지 않는다)
export function AiResultMark() {
  return (
    <Tooltip title="AI가 원문에서 뽑고 원문과 대조한 결과입니다. 사람은 이 칸을 고치지 않습니다.">
      <Tag icon={<RobotOutlined />} bordered={false}>
        AI 결과
      </Tag>
    </Tooltip>
  )
}

// 스키마가 아직 없어 임시 타입·예시 데이터로 그린 화면 표시
export function ExampleDataMark() {
  return (
    <Tooltip title="이 기능의 결과 스키마는 아직 설계 전입니다. 화면 모양을 보려고 만든 예시 데이터입니다.">
      <Tag color="purple" icon={<ExperimentOutlined />}>
        예시 데이터
      </Tag>
    </Tooltip>
  )
}
