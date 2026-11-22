import { App, Button, Input } from 'antd'
import { useState } from 'react'
import { api } from '../api'
import { ApiError } from '../api/errors'
import { isApplicationNumberShape, isDispatchNumberShape } from '../numberShapes'
import { seedRun } from '../runPoll'
import type { ExtractedValueStr } from '../types/generated/OAResult'
import type { NumberEnteredOut } from '../types/provisional/case'
import { HumanCheckTag } from './Marks'
import { StatusTag } from './StatusTag'

// 번호 종류마다 다른 것: 문구, 꼴 검사, 저장 함수 (같은 실행이 이어 도는 PATCH, #70)
// targetId는 출원번호면 case_id(PATCH /cases/{id}), 발송번호면 oa_id(PATCH /oas/{id})
export type NumberKind = 'application_number' | 'dispatch_number'
const KINDS: Record<
  NumberKind,
  {
    label: string
    placeholder: string
    shapeError: string
    isShape: (text: string) => boolean
    save: (targetId: string, value: string) => Promise<NumberEnteredOut>
  }
> = {
  application_number: {
    label: '출원번호',
    placeholder: '10-0000-0000000',
    shapeError: '출원번호 꼴이 아니에요 (숫자 13자리, 예: 10-0000-0000000)',
    isShape: isApplicationNumberShape,
    save: (id, v) => api.setApplicationNumber(id, v),
  },
  dispatch_number: {
    label: '발송번호',
    placeholder: '9-5-0000-000000000',
    shapeError: '발송번호 꼴이 아니에요 (예: 9-5-2099-000000007)',
    isShape: isDispatchNumberShape,
    save: (id, v) => api.setDispatchNumber(id, v),
  },
}

// 번호 입력 칸 (F5 design 6절: 실행 waiting_for_human + waiting_for 가 이 번호 → 사건 머리·올리기 화면에 입력 칸).
// 통지서에서 번호를 확인하지 못해(확인되지 않음·충돌) 실행이 사람을 기다릴 때만 보인다.
// "직접 확인" 꼬리표와 AI가 읽은 값의 상태·후보를 같이 달아 AI가 읽은 값과 사람이 넣을 값을 구분한다.
// 저장 응답의 run_id는 기다리던 같은 실행이 이어 도는 것이라, seedRun으로 queued를 폴링에 넣으면 화면이 다시 받는다.
// 오류는 글과 코드를 그대로 보인다
export function NumberInputForm({
  kind,
  targetId,
  read,
}: {
  kind: NumberKind
  targetId: string
  // 통지서에서 읽은 번호 (정리 결과가 없으면 null)
  read: ExtractedValueStr | null
}) {
  const { message } = App.useApp()
  const k = KINDS[kind]
  const [value, setValue] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const save = async () => {
    if (!k.isShape(value)) {
      setError(k.shapeError)
      return
    }
    setSaving(true)
    setError(null)
    try {
      const out = await k.save(targetId, value.trim())
      message.success(`${k.label}를 넣었어요. 이어서 정리해요`)
      // 같은 실행이 이어 돈다: 응답 run_id를 queued로 넣으면 폴링이 다시 시작되고, 끝나면 화면 데이터를 새로 받는다
      seedRun({ run_id: out.run_id, state: 'queued', current_step: null })
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
        <span className="label1">{k.label}를 넣어 주세요</span>
        <HumanCheckTag />
        {read && <StatusTag status={read.status} />}
      </div>
      <span className="label2 t3">
        통지서에서 {k.label}를 확인하지 못해 정리를 멈췄어요.{' '}
        {candidates.length > 0
          ? `읽은 후보: ${candidates.join(' / ')}`
          : readText
            ? `읽은 글자: ${readText}`
            : '읽은 글자 없음'}
      </span>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Input
          aria-label={k.label}
          placeholder={k.placeholder}
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
