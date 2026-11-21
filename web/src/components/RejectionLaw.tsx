import { Button, Tag } from 'antd'
import { sourceKindLabel } from '../labels'
import type { LegalEvidenceBundle, LegalSource } from '../types/generated/LegalEvidenceBundle'
import { useContext } from 'react'
import { StatusTag } from './StatusTag'
import { SourceContext } from './sourceContext'

// 근거 한 줄의 글자: 종류 · 식별자 · (법령·심사기준은 판본, 판례·심결은 전문/요지)
// 판본을 모르면 "판본 모름"을 그대로 적는다 (현행으로 짐작하지 않음)
function lineText(s: LegalSource): string {
  const tail =
    s.source_kind === 'statute' || s.source_kind === 'guideline'
      ? (s.evidence.edition ?? '판본 모름')
      : s.text_kind
        ? s.text_kind === 'full'
          ? '전문'
          : '요지'
        : null
  return [sourceKindLabel[s.source_kind], s.identifier, tail].filter(Boolean).join(' · ')
}

// "이 거절이유의 법리": 그 거절이유(rejection 번호)에 붙은 법률 근거 묶음을 근거 한 줄씩 보인다.
// - 묶음이 아직 없으면(아직 안 찾음) 이 칸 전체를 그리지 않는다. "찾은 법리 없음"을 지어내지 않는다
// - 묶음은 있는데 근거가 없으면 묶음 상태(조회 범위 내 없음·확인되지 않음)를 그대로 보인다
// - 줄을 누르면 오른쪽 원문 판에 그 근거를 연다. 사람이 근거를 빼거나 고치는 버튼은 없다
export function RejectionLaw({ rejection, legal }: { rejection: number; legal: LegalEvidenceBundle[] }) {
  const { openEvidence } = useContext(SourceContext)
  const bundles = legal.filter((b) => b.rejection === rejection)
  if (bundles.length === 0) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span className="label2 t3" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        이 거절이유의 법리
        <Tag color="purple" bordered={false} style={{ marginInlineEnd: 0 }}>
          AI가 찾아 붙임
        </Tag>
      </span>
      {bundles.map((b) => {
        const sources = b.claims.flatMap((c) => c.sources)
        if (sources.length === 0) {
          return (
            <div key={b.bundle_id}>
              <StatusTag status={b.status} />
            </div>
          )
        }
        return sources.map((s, i) => (
          <div
            key={`${b.bundle_id}-${s.identifier}-${s.evidence.chunk_id ?? i}`}
            style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}
          >
            <Button type="link" size="small" style={{ padding: 0, height: 'auto', textAlign: 'left', whiteSpace: 'normal' }} onClick={() => openEvidence(s, b.checked_on)}>
              {lineText(s)}
            </Button>
            {s.status.value !== 'confirmed' && <StatusTag status={s.status} detail={false} />}
          </div>
        ))
      })}
    </div>
  )
}
