import { Button } from 'antd'
import { editionText, textKindText } from '../format'
import { sourceKindLabel, speakerLabel } from '../labels'
import type { LegalEvidenceBundle, LegalSource } from '../types/generated/LegalEvidenceBundle'
import { useContext } from 'react'
import { AiTag } from './Marks'
import { StatusLine } from './StatusLine'
import { StatusTag } from './StatusTag'
import { SourceContext } from './sourceContext'

// 근거 한 줄의 글자: 종류 · 식별자 · (법령·심사기준은 판본, 판례·심결은 전문/요지)
// 판본을 모르면 "판본 모름"을 그대로 적는다 (현행으로 짐작하지 않음)
function lineText(s: LegalSource): string {
  const tail = editionText(s) ?? textKindText(s)
  return [sourceKindLabel[s.source_kind], s.identifier, tail].filter(Boolean).join(' · ')
}

// 추가 검토할 자료 한 줄: 근거 줄 + 원문 위치 (판례·심결은 선고일·화자까지)
function candidateText(s: LegalSource): string {
  const speaker = s.speaker && speakerLabel[s.speaker]
  // 심사기준은 식별자가 곧 위치라 되풀이하지 않는다
  const location = s.evidence.location === s.identifier ? null : s.evidence.location
  return [lineText(s), location, s.decided_on, speaker].filter(Boolean).join(' · ')
}

// "이 거절이유의 법리": 그 거절이유(rejection 번호)에 붙은 법률 근거 묶음을 근거 한 줄씩 보인다.
// - 묶음이 아직 없으면(아직 안 찾음) 이 칸 전체를 그리지 않는다. "찾은 법리 없음"을 지어내지 않는다
// - 묶음은 있는데 근거가 없으면 묶음 상태(조회 범위 내 없음·확인되지 않음)를 그대로 보인다
// - 줄을 누르면 오른쪽 원문 판에 그 근거를 연다. 사람이 근거를 빼거나 고치는 버튼은 없다
export function RejectionLaw({ rejection, legal }: { rejection: number; legal: LegalEvidenceBundle[] }) {
  const { openEvidence } = useContext(SourceContext)
  const bundles = legal.filter((b) => b.rejection === rejection)
  if (bundles.length === 0) return null
  // 판단 단위가 여럿이면 같은 조각이 되풀이되므로 조각마다 한 번만 보인다
  const candidates = new Map<string, { s: LegalSource; checkedOn: string }>()
  for (const b of bundles) {
    for (const x of b.further_review) {
      if (x.source && !candidates.has(x.chunk_id)) candidates.set(x.chunk_id, { s: x.source, checkedOn: b.checked_on })
    }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span className="label2 t3" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        이 거절이유의 법리
        <AiTag>AI가 찾아 붙임</AiTag>
      </span>
      {bundles.map((b) => {
        const sources = b.claims.flatMap((c) => c.sources)
        if (sources.length === 0) {
          return (
            <div key={b.bundle_id}>
              <StatusLine status={b.status} />
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
      {candidates.size > 0 && (
        <span className="label2 t3" style={{ marginTop: 6 }}>
          추가 검토할 자료 {candidates.size} · 아직 근거로 검토하지 않음, 직접 확인 필요
        </span>
      )}
      {[...candidates].map(([id, { s, checkedOn }]) => (
        <div key={id}>
          <Button type="link" size="small" style={{ padding: 0, height: 'auto', textAlign: 'left', whiteSpace: 'normal' }} onClick={() => openEvidence(s, checkedOn)}>
            {candidateText(s)}
          </Button>
        </div>
      ))}
    </div>
  )
}
