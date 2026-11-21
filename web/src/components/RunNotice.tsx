import { App, Button } from 'antd'
import { useRevalidator } from 'react-router'
import { api } from '../api'
import type { RunSnapshot } from '../runPoll'

// 실패·취소한 실행은 단계 결과가 다 있어도 어디엔가 보여야 한다: 단계 위치와 상관없이 늘 한 줄.
// "다시 돌리기"는 POST /oas/{id}/runs (mock은 처음부터 다시 흉내). 돌린 뒤 loader를 다시 불러 새 실행을 구독한다
export function RunNotice({ oaId, snap }: { oaId: string; snap: RunSnapshot }) {
  const { message } = App.useApp()
  const revalidator = useRevalidator()
  const state = snap.run.state
  if (state !== 'failed' && state !== 'cancelled') return null

  const rerun = async () => {
    try {
      await api.rerunOA(oaId)
      await revalidator.revalidate()
    } catch (e) {
      message.error(`다시 돌리지 못했습니다: ${e instanceof Error ? e.message : String(e)}`)
    }
  }
  return (
    <div className="label2" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', color: state === 'failed' ? 'var(--fg-negative-text)' : undefined }}>
      <span className={state === 'failed' ? undefined : 't3'}>
        {state === 'failed'
          ? `실행이 실패했어요 · ${snap.reason ?? snap.run.current_step ?? '이유를 받지 못했어요'}`
          : '실행을 취소했어요'}
        {' · 다시 돌리면 처음부터 다시 만들어요'}
      </span>
      <Button size="small" onClick={() => void rerun()}>
        다시 돌리기
      </Button>
    </div>
  )
}
