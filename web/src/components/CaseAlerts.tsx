import { Alert, Space } from 'antd'
import { articleLabel } from '../labels'
import type { Rejection } from '../types/generated/OAResult'
import type { DirectionCandidates } from '../types/provisional/direction'
import { HumanCheckTag } from './Marks'
import { StatusTag } from './StatusTag'

// AI가 다루지 않은 거절이유가 남아 있으면 늘 알린다. 번호가 정리 결과에 없어도 번호만이라도 보인다
export function UnsupportedAlert({ numbers, rejections }: { numbers: number[]; rejections: Rejection[] }) {
  if (numbers.length === 0) return null
  const names = numbers.map((no) => {
    const r = rejections.find((x) => x.no === no)
    return r ? `거절이유 ${no}(특허법 ${articleLabel(r.article.value)})` : `거절이유 ${no}`
  })
  return (
    <Alert
      type="warning"
      showIcon
      message={
        <Space wrap>
          <span>{`AI가 다루지 않은 거절이유가 남아 있음: ${names.join(', ')}`}</span>
          <HumanCheckTag>직접 대응 필요</HumanCheckTag>
        </Space>
      }
    />
  )
}

// 보정 제한: 최후면 제한 안내, 모르면(확인되지 않음) "없음"으로 읽히지 않게 따로 알린다
export function AmendmentLimitAlert({ directions }: { directions: DirectionCandidates[] }) {
  if (directions.some((d) => d.amendment_limit === 'unverified')) {
    return (
      <Alert
        type="warning"
        showIcon
        message={
          <Space wrap>
            <span>보정 제한:</span>
            <StatusTag status="unverified" />
            <span>최초·최후거절이유통지 중 어느 것인지 확인하지 못했습니다.</span>
            <HumanCheckTag>통지 종류 직접 확인</HumanCheckTag>
          </Space>
        }
      />
    )
  }
  if (directions.some((d) => d.amendment_limit === 'final')) {
    return (
      <Alert
        type="info"
        showIcon
        message={
          <Space wrap>
            <span>최후거절이유통지: 보정할 수 있는 범위가 제한됩니다 (특허법 제47조제3항).</span>
            <HumanCheckTag>고른 보정이 허용되는 종류인지 직접 확인</HumanCheckTag>
          </Space>
        }
      />
    )
  }
  return null
}
