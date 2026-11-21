import { Alert } from 'antd'
import type { RunSnapshot } from '../runPoll'
import { isRunEnded } from '../runPoll'
import { currentRunText } from '../previousResult'

// 정리 단계 머리: 이전 실행 결과임을 알리고 지금 실행 상태를 한 줄로 보인다
export function PreviousResultNote({ snap }: { snap: RunSnapshot }) {
  // 이미 끝난 실행(실패·취소, 사람 기다림 포함)은 저절로 바뀌지 않는다: 도는 중일 때만 곧 바뀐다고 한다
  // 사람 기다림이면 결과가 열려 이전 결과로 보일 일이 거의 없어 따로 나누지 않았다
  const tail = isRunEnded(snap.run.state) ? '다시 돌리면 새 결과로 바뀌어요.' : '지금 실행이 끝나면 새 결과로 바뀌어요.'
  return (
    <Alert
      type="warning"
      showIcon
      message="이전 실행 결과예요"
      description={`${currentRunText(snap.run)}. ${tail}`}
    />
  )
}
