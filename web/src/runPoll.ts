// 실행 상태 폴링 (결정 D14). React 밖의 일반 모듈이라 단독으로 시험할 수 있다.
// - oaLoader가 latest_run으로 seedRun을 부르면 그 실행의 상태가 여기 들어온다.
// - 화면은 useSyncExternalStore(subscribeRun(id), 스냅숏)으로 구독한다 (hook은 useRunSnapshot.ts).
// - 첫 구독자가 붙고 끝난 상태가 아니면 2.5초 뒤 한 번 GET /runs/{id}만 부르고, 마지막 구독자가 떠나면 멈춘다.
import { api } from './api'
import type { LatestRun, RunState } from './types/provisional/case'

export const POLL_MS = 2500 // 폴링 간격 (판단)

// 화면이 받는 값: 실행 상태 + (상태를 못 받았을 때) 오류 글. 값이 바뀔 때만 새 객체가 된다
export interface RunSnapshot {
  run: LatestRun
  error: string | null
}

// 더 이상 바뀌지 않는 상태 (waiting_for_human은 사람이 고를 때까지 멈춘 것으로 본다)
const ENDED: RunState[] = ['succeeded', 'failed', 'cancelled', 'waiting_for_human']
export const isRunEnded = (state: RunState) => ENDED.includes(state)

interface Entry {
  snap: RunSnapshot
  listeners: Set<() => void>
  timer: ReturnType<typeof setTimeout> | null
}
const entries = new Map<string, Entry>()
// run_id마다 같은 subscribe 함수를 돌려줘야 React가 다시 구독하지 않는다
const subscribers = new Map<string, (onChange: () => void) => () => void>()

// router를 직접 import하면 순환이라, main에서 등록한다 (setRevalidate(() => router.revalidate()))
let revalidate: () => void = () => {}
export function setRevalidate(fn: () => void) {
  revalidate = fn
}

const sameRun = (a: LatestRun, b: LatestRun) => a.state === b.state && a.current_step === b.current_step

function notify(e: Entry) {
  e.listeners.forEach((l) => l())
}

// loader가 받은 latest_run을 넣는다. 달라졌을 때만 새 스냅숏 (같으면 화면을 다시 그리지 않는다)
export function seedRun(run: LatestRun) {
  const e = entries.get(run.run_id)
  if (!e) {
    entries.set(run.run_id, { snap: { run, error: null }, listeners: new Set(), timer: null })
    return
  }
  if (!sameRun(e.snap.run, run) || e.snap.error !== null) {
    e.snap = { run, error: null }
    notify(e)
  }
  schedule(run.run_id)
}

export function getRunSnapshot(runId: string): RunSnapshot | null {
  return entries.get(runId)?.snap ?? null
}

export function subscribeRun(runId: string) {
  let sub = subscribers.get(runId)
  if (!sub) {
    sub = (onChange) => {
      const e = entries.get(runId)
      if (!e) return () => {}
      e.listeners.add(onChange)
      schedule(runId) // 첫 구독자가 붙으면 예약 (이미 있으면 그대로)
      return () => {
        e.listeners.delete(onChange)
        // 마지막 구독자가 떠나면 예약을 지운다: 화면을 떠나면 요청이 멈춘다
        if (e.listeners.size === 0 && e.timer !== null) {
          clearTimeout(e.timer)
          e.timer = null
        }
      }
    }
    subscribers.set(runId, sub)
  }
  return sub
}

// 구독자가 있고 끝나지 않았고 예약이 없을 때만 setTimeout 하나를 건다
function schedule(runId: string) {
  const e = entries.get(runId)
  if (!e || e.timer !== null || e.listeners.size === 0 || isRunEnded(e.snap.run.state)) return
  e.timer = setTimeout(() => void tick(runId), POLL_MS)
}

async function tick(runId: string) {
  const e = entries.get(runId)
  if (!e) return
  e.timer = null
  await refresh(runId, false)
  schedule(runId) // 구독자가 그 사이 떠났거나 끝났으면 걸리지 않는다
}

// GET /runs/{id} 한 번. 바뀐 것을 반영하고, 단계가 바뀌었거나 끝났으면 화면 데이터를 다시 받게 한다.
// force(새로 보기 버튼)면 바뀐 것이 없어도 다시 받는다
async function refresh(runId: string, force: boolean) {
  const e = entries.get(runId)
  if (!e) return
  try {
    const next = await api.getRun(runId)
    const prev = e.snap.run
    const run: LatestRun = { run_id: next.run_id, state: next.state, current_step: next.current_step }
    const stepChanged = run.current_step !== prev.current_step
    const justEnded = isRunEnded(run.state) && !isRunEnded(prev.state)
    if (!sameRun(prev, run) || e.snap.error !== null) {
      e.snap = { run, error: null }
      notify(e)
    }
    if (force || stepChanged || justEnded) revalidate()
  } catch (err) {
    // 조용히 넘기지 않는다: 오류 글을 스냅숏에 넣어 화면이 "상태를 받지 못했어요"를 보이게 한다
    const msg = err instanceof Error ? err.message : String(err)
    if (e.snap.error !== msg) {
      e.snap = { run: e.snap.run, error: msg }
      notify(e)
    }
  }
}

// "새로 보기" 버튼: 이벤트 처리기에서 한 번 부른다
export function refreshRun(runId: string): Promise<void> {
  return refresh(runId, true)
}
