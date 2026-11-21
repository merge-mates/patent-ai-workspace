import { Alert } from 'antd'
import type { RunSnapshot } from '../runPoll'
import { currentRunText } from '../previousResult'

// 정리 단계 머리: 이전 실행 결과임을 알리고 지금 실행 상태를 한 줄로 보인다
export function PreviousResultNote({ snap }: { snap: RunSnapshot }) {
  return (
    <Alert
      type="warning"
      showIcon
      message="이전 실행 결과예요"
      description={`${currentRunText(snap.run)}. 지금 실행이 끝나면 새 결과로 바뀌어요.`}
    />
  )
}
