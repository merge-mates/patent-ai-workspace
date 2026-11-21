import { runStateLabel } from './labels'
import type { LatestRun, OAResultResponse } from './types/provisional/case'

// 서버는 "가장 최근에 끝난(succeeded) 실행"의 결과만 준다 (안 B).
// 그래서 결과의 run_id가 지금 실행(latest_run)과 다르면 지금 보이는 것은 이전 실행 결과다.
// 지금 실행이 아직 없으면(latest_run null) 비교할 것이 없어 이전 결과로 보지 않는다
export function isPreviousResult(oaResult: OAResultResponse | null, latest: LatestRun | null): boolean {
  return oaResult !== null && latest !== null && oaResult.run_id !== latest.run_id
}

// 지금 실행 한 줄: "지금 실행: 실행 중 · 인용발명 대비"
export function currentRunText(run: LatestRun): string {
  return `지금 실행: ${runStateLabel[run.state]}${run.current_step ? ` · ${run.current_step}` : ''}`
}
