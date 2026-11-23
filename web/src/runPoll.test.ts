// runPoll.ts 단위 테스트 (이슈 #197 결정: 화면 코드 가운데 이 파일만 단위 테스트를 둔다).
// 눌러 봐서는 안 보이는 타이머·재시도 동작만 본다. 기대값은 runPoll.ts 맨 위 주석과 이슈 #197 목록에서 가져온다.
// - 첫 구독자가 붙고 끝난 상태가 아니면 2.5초 뒤 한 번 GET /runs/{id}만 부르고, 마지막 구독자가 떠나면 멈춘다.
// - failed·waiting_for_human이면 이유를 한 번 받고, 받기가 실패하면 다음 seedRun에서 다시 묻는다.
// - succeeded면 넘긴 단계(skipped_steps)를 한 번 받고 다시 묻지 않는다 (이슈 #260).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LatestRun, RunStatus } from './types/provisional/case'

// api.getRun만 가짜로 바꿔 끼운다 (서버·fixture를 부르지 않는다)
const getRun = vi.fn<(runId: string) => Promise<RunStatus>>()
vi.mock('./api', () => ({ api: { getRun: (id: string) => getRun(id) } }))

type RunPoll = typeof import('./runPoll')
let rp: RunPoll

const run = (state: LatestRun['state'], current_step: string | null = null): LatestRun => ({
  run_id: 'r_1',
  state,
  current_step,
})
const status = (state: LatestRun['state'], extra: Partial<RunStatus> = {}): RunStatus => ({
  ...run(state),
  oa_id: 'oa_1',
  error: null,
  ...extra,
})

beforeEach(async () => {
  vi.useFakeTimers()
  getRun.mockReset()
  // runPoll은 실행마다 상태를 모듈 안 Map에 둔다: 테스트마다 새로 불러와 앞 테스트 값이 남지 않게 한다
  vi.resetModules()
  rp = await import('./runPoll')
})

afterEach(() => {
  vi.useRealTimers()
})

describe('폴링 타이머', () => {
  it('구독하면 2.5초 뒤 GET /runs/{id}를 한 번만 부른다 (구독자가 둘이어도)', async () => {
    getRun.mockResolvedValue(status('running', { current_step: '거절이유 정리 중' }))
    rp.seedRun(run('running', '통지서 읽는 중'))
    rp.subscribeRun('r_1')(() => {})
    rp.subscribeRun('r_1')(() => {})

    await vi.advanceTimersByTimeAsync(2499)
    expect(getRun).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    expect(getRun).toHaveBeenCalledTimes(1)
    expect(getRun).toHaveBeenCalledWith('r_1')
  })

  it('마지막 구독자가 떠나면 타이머를 지워 더 부르지 않는다', async () => {
    getRun.mockResolvedValue(status('running'))
    rp.seedRun(run('running'))
    const leaveA = rp.subscribeRun('r_1')(() => {})
    const leaveB = rp.subscribeRun('r_1')(() => {})

    leaveA()
    expect(vi.getTimerCount()).toBe(1) // 아직 한 명 남음
    leaveB()
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(getRun).not.toHaveBeenCalled()
  })

  it('안 끝났으면 계속 부르고, 끝난 상태가 되면 타이머를 다시 걸지 않는다', async () => {
    // cancelled: 끝난 상태 중 이유를 따로 받지 않는 것 (succeeded는 넘긴 단계를 받으러 한 번 부른다, 아래 '넘긴 단계 받기')
    // 안 끝났으면 2.5초마다 계속 부르고, 끝난 상태를 받은 뒤로는 멈춘다
    getRun.mockResolvedValueOnce(status('running', { current_step: '인용발명 대비 중' }))
    getRun.mockResolvedValueOnce(status('cancelled'))
    rp.seedRun(run('running'))
    rp.subscribeRun('r_1')(() => {})

    await vi.advanceTimersByTimeAsync(2500)
    expect(getRun).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2500)
    expect(getRun).toHaveBeenCalledTimes(2)
    expect(rp.getRunSnapshot('r_1')?.run.state).toBe('cancelled')
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(getRun).toHaveBeenCalledTimes(2)
  })

  it('처음부터 끝난 상태로 들어온 실행은 구독해도 걸지 않는다', async () => {
    rp.seedRun(run('cancelled'))
    rp.subscribeRun('r_1')(() => {})
    await vi.advanceTimersByTimeAsync(10_000)
    expect(getRun).not.toHaveBeenCalled()
  })
})

describe('이유 받기 (failed·waiting_for_human)', () => {
  it('failed면 구독 없이도 이유를 한 번 받고, 같은 상태로 다시 넣어도 다시 묻지 않는다', async () => {
    getRun.mockResolvedValue(status('failed', { error: { code: 'tool_error', message: '도구 오류' } }))
    rp.seedRun(run('failed'))
    await vi.advanceTimersByTimeAsync(0)
    expect(getRun).toHaveBeenCalledTimes(1)
    expect(rp.getRunSnapshot('r_1')?.reason).toBe('도구 오류')

    rp.seedRun(run('failed'))
    await vi.advanceTimersByTimeAsync(10_000)
    expect(getRun).toHaveBeenCalledTimes(1)
  })

  it('waiting_for_human이면 기다리는 이유를 한 번 받는다', async () => {
    getRun.mockResolvedValue(status('waiting_for_human', { waiting_for: 'direction_selection' }))
    rp.seedRun(run('waiting_for_human'))
    rp.subscribeRun('r_1')(() => {})
    await vi.advanceTimersByTimeAsync(10_000)
    expect(getRun).toHaveBeenCalledTimes(1)
    expect(rp.getRunSnapshot('r_1')?.waitingFor).toBe('direction_selection')
  })

  it('번호를 넣어 같은 실행이 queued로 이어지면 기다림 이유를 버리고 폴링을 다시 시작한다', async () => {
    getRun.mockResolvedValueOnce(status('waiting_for_human', { waiting_for: 'dispatch_number' }))
    rp.seedRun(run('waiting_for_human'))
    rp.subscribeRun('r_1')(() => {})
    await vi.advanceTimersByTimeAsync(10_000)
    expect(rp.getRunSnapshot('r_1')?.waitingFor).toBe('dispatch_number')
    getRun.mockReset()

    // 발송번호 PATCH 응답의 run_id(같은 실행)를 queued로 넣는다
    getRun.mockResolvedValue(status('succeeded'))
    // 끝나면 화면 데이터를 새로 받는다 (router.revalidate 자리에 감시 함수를 건다)
    const spy = vi.fn()
    rp.setRevalidate(spy)
    rp.seedRun({ run_id: 'r_1', state: 'queued', current_step: null })
    expect(rp.getRunSnapshot('r_1')?.run.state).toBe('queued')
    expect(rp.getRunSnapshot('r_1')?.waitingFor).toBeNull()
    await vi.advanceTimersByTimeAsync(2500)
    expect(getRun).toHaveBeenCalledWith('r_1')
    expect(rp.getRunSnapshot('r_1')?.run.state).toBe('succeeded')
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('이유 받기가 실패하면 오류를 보이고, 다음 seedRun에서 다시 묻는다', async () => {
    getRun.mockRejectedValueOnce(new Error('네트워크 오류'))
    getRun.mockResolvedValueOnce(status('failed', { error: { code: 'tool_error', message: '도구 오류' } }))
    rp.seedRun(run('failed'))
    await vi.advanceTimersByTimeAsync(0)
    expect(getRun).toHaveBeenCalledTimes(1)
    expect(rp.getRunSnapshot('r_1')?.error).toBe('네트워크 오류')

    rp.seedRun(run('failed'))
    await vi.advanceTimersByTimeAsync(0)
    expect(getRun).toHaveBeenCalledTimes(2)
    expect(rp.getRunSnapshot('r_1')).toMatchObject({ error: null, reason: '도구 오류' })
  })
})

describe('넘긴 단계 받기 (succeeded, 이슈 #260)', () => {
  const skippedSteps = [{ step: 'run_f3', reason: 'input_unverified: 앞 단계인 OA 거절이유 정리 결과가 없음' }]

  it('succeeded면 넘긴 단계를 한 번 받고 다시 안 묻는다', async () => {
    getRun.mockResolvedValue(status('succeeded', { skipped_steps: skippedSteps }))
    rp.seedRun(run('succeeded'))
    await vi.advanceTimersByTimeAsync(0)
    expect(getRun).toHaveBeenCalledTimes(1)
    expect(rp.getRunSnapshot('r_1')?.skipped).toEqual(skippedSteps)

    rp.seedRun(run('succeeded'))
    rp.subscribeRun('r_1')(() => {})
    await vi.advanceTimersByTimeAsync(10_000)
    expect(getRun).toHaveBeenCalledTimes(1)
  })

  it('지켜보던 실행이 succeeded로 끝나면 그 응답의 넘긴 단계를 쓰고 뒤따르는 seedRun에서 또 묻지 않는다', async () => {
    getRun.mockResolvedValue(status('succeeded', { skipped_steps: skippedSteps }))
    rp.seedRun(run('running', '인용발명 대비 중'))
    rp.subscribeRun('r_1')(() => {})
    await vi.advanceTimersByTimeAsync(2500)
    expect(getRun).toHaveBeenCalledTimes(1)
    expect(rp.getRunSnapshot('r_1')?.skipped).toEqual(skippedSteps)

    // 끝나면 화면 데이터를 다시 받고(revalidate) loader가 같은 실행을 succeeded로 다시 넣는다
    rp.seedRun(run('succeeded'))
    await vi.advanceTimersByTimeAsync(10_000)
    expect(getRun).toHaveBeenCalledTimes(1)
  })
})

// 방향을 고르면 서버가 초안만 다시 만드는 작은 실행을 만든다. 화면이 그 실행을 "고르기로 시작한 것"으로 표시해 둔다
// (그동안 사건 머리·단계 막대가 "이전 실행 결과"라고 지나치게 말하지 않게). 기대값은 이슈 #43 지시문에서 가져왔다.
describe('고르기로 시작한 작은 실행 표시', () => {
  it('표시한 실행을 loader가 같은 run_id로 다시 seedRun해도 표시가 남는다', () => {
    rp.markSelectionRun('r_1')
    rp.seedRun(run('queued'))
    rp.seedRun(run('running', '초안 다시 만드는 중'))
    expect(rp.getRunSnapshot('r_1')?.fromSelection).toBe(true)
  })

  it('표시하지 않은 실행은 표시가 없다 (전체 다시 돌리기 등)', () => {
    rp.seedRun(run('running'))
    expect(rp.getRunSnapshot('r_1')?.fromSelection).toBe(false)
    expect(rp.isSelectionRunActive(rp.getRunSnapshot('r_1'))).toBe(false)
  })

  it('표시한 실행이 queued·running인 동안만 도는 중이고, succeeded·failed·cancelled가 되면 거짓이다', () => {
    rp.markSelectionRun('r_1')
    rp.seedRun(run('queued'))
    expect(rp.isSelectionRunActive(rp.getRunSnapshot('r_1'))).toBe(true)
    rp.seedRun(run('running'))
    expect(rp.isSelectionRunActive(rp.getRunSnapshot('r_1'))).toBe(true)
    getRun.mockResolvedValue(status('succeeded'))
    rp.seedRun(run('succeeded'))
    expect(rp.isSelectionRunActive(rp.getRunSnapshot('r_1'))).toBe(false)
    rp.seedRun(run('failed'))
    expect(rp.isSelectionRunActive(rp.getRunSnapshot('r_1'))).toBe(false)
    rp.seedRun(run('cancelled'))
    expect(rp.isSelectionRunActive(rp.getRunSnapshot('r_1'))).toBe(false)
  })

  it('표시하면 그 실행을 구독한 화면이 다시 그려진다', () => {
    rp.seedRun(run('queued'))
    const onChange = vi.fn()
    rp.subscribeRun('r_1')(onChange)
    rp.markSelectionRun('r_1')
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('아직 모르는 run_id를 표시하면 queued로 시작한다', () => {
    rp.markSelectionRun('r_9')
    const s = rp.getRunSnapshot('r_9')
    expect(s?.run.state).toBe('queued')
    expect(rp.isSelectionRunActive(s)).toBe(true)
  })
})

// 실제 길: 2.5초 폴링(refresh)을 지나도 표시가 남는지
describe('고르기로 시작한 작은 실행 표시: 폴링을 지나도', () => {
  it('폴링으로 running·succeeded를 받아도 표시가 남고, 끝나면 도는 중이 거짓이다', async () => {
    rp.markSelectionRun('r_1')
    rp.seedRun(run('queued'))
    rp.subscribeRun('r_1')(() => {})

    getRun.mockResolvedValue(status('running', { current_step: '초안 다시 만드는 중' }))
    await vi.advanceTimersByTimeAsync(2500)
    let s = rp.getRunSnapshot('r_1')
    expect(s?.run.state).toBe('running')
    expect(s?.fromSelection).toBe(true)
    expect(rp.isSelectionRunActive(s)).toBe(true)

    getRun.mockResolvedValue(status('succeeded'))
    await vi.advanceTimersByTimeAsync(2500)
    s = rp.getRunSnapshot('r_1')
    expect(s?.run.state).toBe('succeeded')
    expect(s?.fromSelection).toBe(true)
    expect(rp.isSelectionRunActive(s)).toBe(false)
  })

  it('폴링이 실패해 오류 글이 들어가도 표시가 남는다', async () => {
    rp.markSelectionRun('r_1')
    rp.seedRun(run('running'))
    rp.subscribeRun('r_1')(() => {})
    getRun.mockRejectedValue(new Error('network'))
    await vi.advanceTimersByTimeAsync(2500)
    const s = rp.getRunSnapshot('r_1')
    expect(s?.error).toBe('network')
    expect(s?.fromSelection).toBe(true)
  })
})
