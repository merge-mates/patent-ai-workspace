import { Alert, Space } from 'antd'
import type { NoticeKind } from '../types/generated/OAResult'
import { HumanCheckTag } from './Marks'
import { StatusTag } from './StatusTag'

// 보정 제한: OA 하나에 하나라 ① OAResult.notice_kind에서 정한다 (묶음마다 두지 않음).
// 최후면 제한 안내, 모르면(unknown·값 없음·정리 결과 없음) "없음"으로 읽히지 않게 "확인되지 않음"으로 알린다
export function AmendmentLimitAlert({ noticeKind }: { noticeKind: NoticeKind | null }) {
  if (noticeKind === null || noticeKind === 'unknown') {
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
  if (noticeKind === 'final') {
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
