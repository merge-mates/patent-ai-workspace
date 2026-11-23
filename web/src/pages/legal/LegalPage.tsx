import { Alert, Button, Checkbox, DatePicker, Input, Select } from 'antd'
import { useState } from 'react'
import { api } from '../../api'
import { LegalBundleView } from '../../components/LegalBundleView'
import { sourceKindLabel } from '../../labels'
import type { LegalEvidenceBundle, LegalSourceKind } from '../../types/generated/LegalEvidenceBundle'

// 찾을 곳 순서는 디자인 B 고친 판(PQuestion): 법령 · 판례 · 심결 · 심사기준
const KINDS: LegalSourceKind[] = ['statute', 'precedent', 'trial', 'guideline']
const EXAMPLES = ['진보성 판단에서 결합 동기는 어디서 찾나', '특허법 제42조제4항제2호', "청구항 '상기' 표현이 앞에 없을 때"]

// 시점 고르기: 현행 / 날짜 고르기 (디자인의 Select)
const WHEN_OPTIONS = [
  { value: 'current', label: '현행' },
  { value: 'pick', label: '날짜 고르기' },
]

// 질문 하나 + 그 답 (서버가 질문 하나 → 답 하나라, 화면에서 쌍을 위로 쌓는다)
interface Turn {
  text: string
  answer: LegalEvidenceBundle
  scopeChanged: boolean // 앞 질문과 시점·자료 유형이 바뀌어 새 범위로 찾았는가
}

// 법률 질문 (사건 없이, 디자인 PQuestion): 질문·답 쌍이 위에서 아래로 쌓이고, 입력줄은 맨 아래에 붙는다
export function LegalPage() {
  const [text, setText] = useState('')
  const [when, setWhen] = useState<'current' | 'pick'>('current')
  const [asOf, setAsOf] = useState<string | null>(null) // null = 현행
  const [kinds, setKinds] = useState<LegalSourceKind[]>([]) // 비면 모든 유형
  const [turns, setTurns] = useState<Turn[]>([])
  // 첫 답에서 받은 대화 ID: 다음 질문에 넘겨 같은 대화로 잇는다. null이면 다음 질문이 새 대화
  const [chatId, setChatId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 질문을 보내고 답을 받는다 (버튼·엔터를 눌렀을 때만 부른다)
  const ask = async () => {
    const q = text.trim()
    if (!q || needDate) return
    setBusy(true)
    setError(null)
    try {
      const res = await api.askLegal({ text: q, as_of: when === 'pick' ? asOf : null, source_kinds: kinds }, chatId ?? undefined)
      setChatId(res.chat_id)
      setTurns([...turns, { text: q, answer: res.answer, scopeChanged: res.scope_changed }])
      setText('')
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  // "날짜 고르기"인데 날짜가 비면 현행으로 잘못 보내지 않게 묻기를 막는다
  const needDate = when === 'pick' && !asOf

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 'calc(100vh - 57px)' }}>
      <section
        className="legal-section"
        style={{
          width: '100%',
          maxWidth: 920,
          margin: '0 auto',
          padding: '32px 40px 40px',
          display: 'flex',
          flexDirection: 'column',
          gap: 28,
          flex: '1 1 auto',
          boxSizing: 'border-box',
        }}
      >
        {turns.length === 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <h1 className="heading1">법률 질문</h1>
            <span className="body2 t2">질문, 쟁점, 키워드, 조문(예: 특허법 제29조제2항), 사건번호를 넣으세요.</span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span className="label2 t3">예</span>
              {EXAMPLES.map((q) => (
                <Button key={q} type="link" style={{ alignSelf: 'flex-start', padding: 0, height: 'auto' }} onClick={() => setText(q)}>
                  {q}
                </Button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
            {/* 사용자 질문: 오른쪽 말풍선 */}
            <div
              style={{
                alignSelf: 'flex-end',
                maxWidth: 560,
                padding: '12px 16px',
                borderRadius: 16,
                background: 'var(--bg-neutral-secondary)',
              }}
            >
              <span className="body2">{t.text}</span>
            </div>
            {t.scopeChanged && (
              <Alert type="info" showIcon banner message="앞 질문과 시점·자료 유형이 바뀌어 새 범위로 찾았어요" />
            )}
            <LegalBundleView b={t.answer} />
          </div>
        ))}
        {error && <Alert type="error" showIcon message={`답을 받지 못했습니다: ${error}`} />}
      </section>

      {/* 입력줄: 화면 아래에 붙는다 */}
      <div
        style={{
          position: 'sticky',
          bottom: 0,
          background: '#fff',
          borderTop: '1px solid var(--line-neutral-tertiary)',
        }}
      >
        <div
          className="legal-section"
          style={{
            maxWidth: 920,
            margin: '0 auto',
            padding: '16px 40px 8px',
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            boxSizing: 'border-box',
          }}
        >
          <Input.Search
            size="large"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onSearch={ask}
            loading={busy}
            enterButton={<Button type="primary" disabled={needDate}>묻기</Button>}
            placeholder="이어서 물어보세요. 질문, 쟁점, 키워드, 사건번호 다 돼요"
          />
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className="label2 t3">시점</span>
            <Select
              size="small"
              value={when}
              options={WHEN_OPTIONS}
              style={{ width: 120 }}
              onChange={(v) => {
                setWhen(v)
                if (v === 'current') setAsOf(null)
              }}
            />
            {when === 'pick' && (
              <DatePicker
                size="small"
                placeholder="날짜 지정"
                onChange={(_, s) => setAsOf(typeof s === 'string' && s ? s : null)}
              />
            )}
            {needDate && <span className="label2" style={{ color: 'var(--fg-cautionary-text)' }}>날짜를 골라 주세요</span>}
            <span className="label2 t3" style={{ marginLeft: 8 }}>
              찾을 곳
            </span>
            <Checkbox.Group
              options={KINDS.map((k) => ({ value: k, label: sourceKindLabel[k] }))}
              value={kinds}
              onChange={(v) => setKinds(v as LegalSourceKind[])}
            />
            <span className="label2 t3">아무것도 안 고르면 모든 유형</span>
            {/* 앞 질문 맥락을 끊고 새 대화로 시작한다 */}
            {turns.length > 0 && (
              <Button
                type="link"
                size="small"
                onClick={() => {
                  setTurns([])
                  setChatId(null)
                  setError(null)
                }}
              >
                새 질문 시작
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
