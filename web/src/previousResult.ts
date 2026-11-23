import { runStateLabel } from './labels'
import { isSelectionRunActive, type RunSnapshot } from './runPoll'
import type { LatestRun, OAResultResponse } from './types/provisional/case'

// 서버는 "가장 최근에 끝난(succeeded) 실행"의 결과만 준다 (안 B).
// 그래서 결과의 run_id가 지금 실행(latest_run)과 다르면 지금 보이는 것은 이전 실행 결과다.
// 지금 실행이 아직 없으면(latest_run null) 비교할 것이 없어 이전 결과로 보지 않는다
// 단, 지금 실행이 화면이 방금 고르기·직접 쓰기로 시작한 작은 실행이고 아직 도는 중이면 정리·대비·방향은 그대로 옮겨지므로
// 이전 결과로 말하지 않는다 (4단계 초안만 "다시 만드는 중"). snap은 그 실행의 폴링 스냅숏
export function isPreviousResult(
  oaResult: OAResultResponse | null,
  latest: LatestRun | null,
  snap: RunSnapshot | null = null,
): boolean {
  if (isSelectionRunActive(snap)) return false
  return oaResult !== null && latest !== null && oaResult.run_id !== latest.run_id
}

// 지금 실행 한 줄: "지금 실행: 실행 중 · 인용발명 대비"
export function currentRunText(run: LatestRun): string {
  return `지금 실행: ${runStateLabel[run.state]}${run.current_step ? ` · ${run.current_step}` : ''}`
}
