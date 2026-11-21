import type { Status } from '../types/generated/OAResult'
import { StatusTag } from './StatusTag'

// 상태 한 줄: 확인됨은 꼬리표 없이 초록 글자("확인됨 · 무엇을 확인했나"), 나머지(확인되지 않음·조회 범위 내 없음·충돌)만 꼬리표
// (근거·인용 줄처럼 글자로 읽는 자리에 쓴다. 표 칸은 StatusTag compact)
export function StatusLine({ status, unverifiedText }: { status: Status; unverifiedText?: string }) {
  if (status.value === 'confirmed') {
    return (
      <span className="label1" style={{ color: 'var(--fg-positive-text)' }}>
        확인됨{status.checked ? ` · ${status.checked}` : ''}
      </span>
    )
  }
  return <StatusTag status={status} unverifiedText={unverifiedText} />
}
