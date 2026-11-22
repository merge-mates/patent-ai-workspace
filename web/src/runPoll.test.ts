// runPoll.ts 단위 테스트 (이슈 #197 결정: 화면 코드 가운데 이 파일만 단위 테스트를 둔다).
// 눌러 봐서는 안 보이는 타이머·재시도 동작만 본다. 기대값은 runPoll.ts 맨 위 주석과 이슈 #197 목록에서 가져온다.
// - 첫 구독자가 붙고 끝난 상태가 아니면 2.5초 뒤 한 번 GET /runs/{id}만 부르고, 마지막 구독자가 떠나면 멈춘다.
// - failed·waiting_for_human이면 이유를 한 번 받고, 받기가 실패하면 다음 seedRun에서 다시 묻는다.
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
    // cancelled: 끝난 상태 중 이유를 따로 받지 않는 것 (succeeded는 #260에서 넘긴 단계를 받으러 한 번 부르게 된다)
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
