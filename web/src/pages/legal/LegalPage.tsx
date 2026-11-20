import { SendOutlined } from '@ant-design/icons'
import { Alert, Button, Card, DatePicker, Input, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import { api } from '../../api'
import { LegalBundleView } from '../../components/LegalBundleView'
import { sourceKindLabel } from '../../labels'
import { AiResultMark, ExampleDataMark } from '../../components/Marks'
import type { LegalEvidenceBundle, LegalSourceKind } from '../../types/generated/LegalEvidenceBundle'

const KINDS: LegalSourceKind[] = ['statute', 'exam_guideline', 'precedent', 'trial_decision']
const EXAMPLES = ['진보성 판단에서 결합 동기는 어디서 찾나', '특허법 제42조제4항제2호', "청구항 '상기' 표현이 앞에 없을 때"]

// 법률 질문 (사건 없이): 입력창 하나 + 선택 칩(시점, 자료 유형) → 주장마다 근거
export function LegalPage() {
  const [text, setText] = useState('')
  const [asOf, setAsOf] = useState<string | null>(null) // null = 현행
  const [pickerKey, setPickerKey] = useState(0) // 바꾸면 날짜 칸이 비워진다
  const [kinds, setKinds] = useState<LegalSourceKind[]>([]) // 비면 모든 유형
  const [answer, setAnswer] = useState<LegalEvidenceBundle | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggleKind = (k: LegalSourceKind, on: boolean) =>
    setKinds(on ? [...kinds, k] : kinds.filter((x) => x !== k))

  // 질문을 보내고 답을 받는다 (버튼을 눌렀을 때만 부른다)
  const ask = async () => {
    if (!text.trim()) return
    setBusy(true)
    setError(null)
    try {
      setAnswer(await api.askLegal({ text: text.trim(), as_of: asOf, source_kinds: kinds }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%', maxWidth: 960, margin: '0 auto', display: 'flex' }}>
      <Card size="small" title="법률 질문">
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          <Input.TextArea
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoSize={{ minRows: 2, maxRows: 6 }}
            placeholder="질문, 키워드, 조문(예: 특허법 제29조제2항), 사건번호를 넣으세요"
          />
          <Space size={[4, 4]} wrap>
            <Typography.Text type="secondary">시점</Typography.Text>
            <Tag.CheckableTag checked={asOf === null} onChange={() => {
                setAsOf(null)
                setPickerKey(pickerKey + 1)
              }}>
              현행
            </Tag.CheckableTag>
            <DatePicker
              key={pickerKey}
              size="small"
              placeholder="날짜 지정"
              onChange={(_, s) => setAsOf(typeof s === 'string' && s ? s : null)}
            />
            <Typography.Text type="secondary" style={{ marginInlineStart: 12 }}>
              자료 유형
            </Typography.Text>
            {KINDS.map((k) => (
              <Tag.CheckableTag key={k} checked={kinds.includes(k)} onChange={(on) => toggleKind(k, on)}>
                {sourceKindLabel[k]}
              </Tag.CheckableTag>
            ))}
          </Space>
          <Space wrap>
            <Button type="primary" icon={<SendOutlined />} loading={busy} onClick={ask} disabled={!text.trim()}>
              묻기
            </Button>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              예:
            </Typography.Text>
            {EXAMPLES.map((q) => (
              <Typography.Link key={q} style={{ fontSize: 12 }} onClick={() => setText(q)}>
                {q}
              </Typography.Link>
            ))}
          </Space>
        </Space>
      </Card>
      {error && <Alert type="error" showIcon message={`답을 받지 못했습니다: ${error}`} />}
      {answer && (
        <Card
          size="small"
          title={
            <Space>
              답변 <AiResultMark /> <ExampleDataMark />
            </Space>
          }
        >
          <LegalBundleView b={answer} />
        </Card>
      )}
    </Space>
  )
}
