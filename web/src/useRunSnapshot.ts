import { useSyncExternalStore } from 'react'
import { getRunSnapshot, subscribeRun, type RunSnapshot } from './runPoll'
import type { LatestRun } from './types/provisional/case'

// 화면이 실행 상태를 구독한다 (결정 D14). loader가 받은 run은 폴링이 시작되기 전 값일 때만 쓴다
// 반환 객체는 폴링 값이 바뀔 때만 새로 만들어진다 (같은 값이면 같은 객체)
// 실행 줄이 아직 없으면(latest_run null) 구독하지 않고 null을 돌려준다 (훅은 늘 같은 순서로 부른다)
const fallbacks = new WeakMap<LatestRun, RunSnapshot>()
const noSubscribe = () => () => {}
const noSnapshot = () => null
export function useRunSnapshot(loaderRun: LatestRun | null): RunSnapshot | null {
  const runId = loaderRun?.run_id ?? null
  const snap = useSyncExternalStore(
    runId === null ? noSubscribe : subscribeRun(runId),
    runId === null ? noSnapshot : () => getRunSnapshot(runId),
  )
  if (loaderRun === null) return null
  if (snap) return snap
  let f = fallbacks.get(loaderRun)
  if (!f) {
    f = { run: loaderRun, error: null, reason: null }
    fallbacks.set(loaderRun, f)
  }
  return f
}
