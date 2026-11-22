import { App, Button, Input } from 'antd'
import { useState } from 'react'
import { api } from '../api'
import { ApiError } from '../api/errors'
import { refreshRun } from '../runPoll'
import type { ExtractedValueStr } from '../types/generated/OAResult'
import { HumanCheckTag } from './Marks'
import { StatusTag } from './StatusTag'

// 출원번호 입력 칸 (F5 design 6절 "출원번호 입력 기다림": 실행 waiting_for_human + waiting_for application_number → 사건 머리에 입력 칸).
// 통지서에서 출원번호를 확인하지 못해(확인되지 않음·충돌) 실행이 사람을 기다릴 때만 보인다.
// 입력을 요청하는 줄에 "직접 확인" 꼬리표와 AI가 읽은 값의 상태(충돌 등)를 같이 단다 (AI가 읽은 값과 사람이 넣을 값을 구분).
// 저장은 PATCH /cases/{id} 자리 (api.setApplicationNumber). 서버에 아직 없으면 오류 글을 그대로 보인다
export function ApplicationNumberForm({
  caseId,
  runId,
  read,
}: {
  caseId: string
  runId: string
  // 통지서에서 읽은 출원번호 (정리 결과가 없으면 null)
  read: ExtractedValueStr | null
}) {
  const { message } = App.useApp()
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  // 한국 출원번호 꼴만 가볍게 본다: 하이픈을 빼고 숫자 13자리 (서버가 다시 맞춘다)
  const digits = value.replace(/-/g, '').trim()
  const wellFormed = /^\d{13}$/.test(digits)

  const save = async () => {
    if (!wellFormed) {
      setError('출원번호 꼴이 아니에요 (숫자 13자리, 예: 10-0000-0000000)')
      return
    }
    setSaving(true)
    setError(null)
    try {
      await api.setApplicationNumber(caseId, value.trim())
      message.success('출원번호를 넣었어요. 이어서 정리해요')
      // 기다리던 실행 상태를 다시 받고 화면 데이터도 새로 받는다
      await refreshRun(runId)
    } catch (e) {
      setError(e instanceof ApiError ? `${e.message} (${e.code})` : e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  // 통지서에서 읽은 글자·후보 (충돌이면 후보를 나란히, 고르지 않음)
  const candidates = read?.candidates?.map((c) => c.raw_text ?? c.value).filter((x) => x) ?? []
  const readText = read?.raw_text ?? read?.value ?? null

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: '12px 16px',
        marginTop: 8,
        maxWidth: 560,
        borderRadius: 8,
        background: 'var(--bg-neutral-secondary)',
        border: '1px solid var(--line-neutral-secondary)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className="label1">출원번호를 넣어 주세요</span>
        <HumanCheckTag />
        {read && <StatusTag status={read.status} />}
      </div>
      <span className="label2 t3">
        통지서에서 출원번호를 확인하지 못해 정리를 멈췄어요.{' '}
        {candidates.length > 0
          ? `읽은 후보: ${candidates.join(' / ')}`
          : readText
            ? `읽은 글자: ${readText}`
            : '읽은 글자 없음'}
      </span>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Input
          aria-label="출원번호"
          placeholder="10-0000-0000000"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onPressEnter={() => void save()}
          style={{ flex: '1 1 220px', maxWidth: 280 }}
          status={error ? 'error' : undefined}
        />
        <Button type="primary" loading={saving} onClick={() => void save()}>
          넣기
        </Button>
      </div>
      {error && (
        <span className="label2" style={{ color: 'var(--fg-negative-text)' }}>
          {error}
        </span>
      )}
    </div>
  )
}
