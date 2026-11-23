import { App, Button } from 'antd'
import { useState } from 'react'
import { useRevalidator } from 'react-router'
import { api } from '../api'
import { ApiError } from '../api/errors'
import { confirmedAtText } from '../format'
import type { ConfirmationOut } from '../types/provisional/case'
import { HumanTag } from './Marks'

// 정리 결과 "맞아요" (PUT·GET /oas/{id}/oa-result/confirmation, #70). 사람이 지금 보이는 OA 정리를 확인했다고 남기는 줄.
// 확인 전: 버튼. 확인 뒤: 사람 꼬리표 + 확인 시각 + "다시 확인"(시각만 새로). AI 결과 꼬리표와 다른 검정 사람 꼬리표를 쓴다.
// 확인은 그 정리를 낸 실행(run_id)에 붙는다: 응답 run_id가 지금 보이는 정리와 다르면 확인으로 보지 않는다
export function OAResultConfirm({
  oaId,
  runId,
  confirmation,
  running,
}: {
  oaId: string
  // 지금 보이는 OA 정리를 낸 실행 (oaResult.run_id)
  runId: string
  // loader가 받은 확인 상태 (모르면 null)
  confirmation: ConfirmationOut | null
  // 그 OA의 최근 실행이 아직 도는 중(queued·running). 도는 동안은 새 정리가 곧 나오니 버튼을 막는다.
  // (막지 못한 틈에 정리가 바뀌어도 서버가 본 run_id와 비교해 409로 막는다, #311)
  running: boolean
}) {
  const { message } = App.useApp()
  const revalidator = useRevalidator()
  // 방금 누른 응답: 화면에 바로 보이고, 그 뒤 loader가 새로 받는다
  const [pressed, setPressed] = useState<ConfirmationOut | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 지금 보이는 정리(runId)의 확인만 센다
  const own = [pressed, confirmation].find((c) => c !== null && c.run_id === runId) ?? null
  const confirmedAt = own?.confirmed_at ?? null
  // 확인 여부를 못 받았다(GET 실패 등): "확인 전"으로 그리지 않고 모름으로 보인다
  const unknown = pressed === null && confirmation === null
  // 실행이 막 끝나 화면이 새 정리를 다시 받는 중(revalidate)일 때도 막는다: 그 사이엔 옛 정리가 보여 누르면 409가 난다
  const busy = running || revalidator.state !== 'idle'

  const confirm = async () => {
    setSaving(true)
    setError(null)
    try {
      // 화면에 보이는 정리(runId)를 함께 보낸다. 서버는 지금 정리와 다르면 확인을 남기지 않는다 (#311)
      const out = await api.confirmOAResult(oaId, runId)
      setPressed(out)
      await revalidator.revalidate()
    } catch (e) {
      // 그 사이 새 정리가 나왔다(409 stale_result): 확인은 안 남았다. 새 정리를 받아 다시 보게 한다
      if (e instanceof ApiError && e.code === 'stale_result') {
        message.warning('그 사이 새 정리가 나와 확인을 남기지 않았어요. 새 정리를 보고 다시 확인해 주세요')
        await revalidator.revalidate()
        return
      }
      setError(e instanceof ApiError ? `${e.message} (${e.code})` : e instanceof Error ? e.message : String(e))
      message.error('정리 확인을 남기지 못했어요')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
      {confirmedAt !== null ? (
        <>
          <HumanTag>직접 확인함</HumanTag>
          <span className="label2 t3">{confirmedAtText(confirmedAt)}</span>
          <Button size="small" loading={saving} disabled={busy} onClick={() => void confirm()}>
            다시 확인
          </Button>
        </>
      ) : (
        <>
          <Button type="primary" size="small" loading={saving} disabled={busy} onClick={() => void confirm()}>
            정리 결과 맞아요
          </Button>
          <span className="label2 t3">
            {running
              ? '새 정리가 나오는 중이에요 · 끝난 뒤 확인해 주세요'
              : unknown
                ? '확인 여부 (모름): 확인 상태를 받지 못했어요'
                : 'AI가 정리한 것을 확인했다고 남겨요'}
          </span>
        </>
      )}
      {confirmedAt !== null && running && (
        <span className="label2 t3">새 정리가 나오는 중이에요 · 끝난 뒤 다시 확인해 주세요</span>
      )}
      {error && (
        <span className="label2" style={{ color: 'var(--fg-negative-text)' }}>
          {error}
        </span>
      )}
    </div>
  )
}
