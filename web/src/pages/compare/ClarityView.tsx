import { Button } from 'antd'
import { type ReactNode, useContext } from 'react'
import { CoreLabel } from '../../components/Marks'
import { SourceContext } from '../../components/sourceContext'
import { StatusTag } from '../../components/StatusTag'
import { COMPARE_UNVERIFIED_TEXT } from '../../labels'
import { claimRange, sentence, claimLocationText, termText } from '../../format'
import type { ClarityReview } from '../../types/generated/ClarityReview'
import type { JudgmentUnit } from '../../types/generated/JudgmentUnit'

// 한 줄: 왼쪽 이름 · 글 · 오른쪽 원문 링크
function Row({ label, children, link }: { label: string; children: ReactNode; link?: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        padding: '14px 0',
        borderBottom: '1px solid var(--line-neutral-tertiary)',
        flexWrap: 'wrap',
        alignItems: 'center',
      }}
    >
      <span className="label1 t3" style={{ width: 120 }}>
        {label}
      </span>
      <span className="body2" style={{ flex: '1 1 320px', overflowWrap: 'anywhere' }}>
        {children}
      </span>
      {link}
    </div>
  )
}

// 명확성: 핵심(AI 제안) 한 줄 + 청구항에서 / 함께 읽은 청구항 / 명세서에서 (데이터에 있는 줄만)
export function ClarityView({ c, unit }: { c: ClarityReview; unit: JudgmentUnit }) {
  const { openCite } = useContext(SourceContext)
  const def = c.spec_definition
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <CoreLabel />
        <h2 className="heading1" style={{ fontSize: 24, lineHeight: '32px' }}>
          청구항 {c.claim}의 “{termText(c.term)}”
        </h2>
        <p className="body1 t2">{sentence(c.note)} 판정은 하지 않아요.</p>
        {c.status.value !== 'confirmed' && (
          <div>
            <StatusTag status={c.status} unverifiedText={COMPARE_UNVERIFIED_TEXT} />
          </div>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <Row label="청구항에서">{claimLocationText(null, c.claim_location)}</Row>
        {unit.read_with.length > 0 && (
          <Row label="함께 읽은 청구항">청구항 {claimRange(unit.read_with)}</Row>
        )}
        <Row
          label="명세서에서"
          link={
            def && (
              <Button
                type="link"
                size="small"
                onClick={() => openCite({ title: `명세서 ${def.location ?? ''}`.trim(), items: [def], status: c.status, note: null, unverifiedText: COMPARE_UNVERIFIED_TEXT })}
              >
                명세서 {def.location ?? ''}
              </Button>
            )
          }
        >
          {def ? (
            <>{def.raw_text ? `“${def.raw_text}”` : '정의가 있는 위치만 알아요.'}</>
          ) : (
            <>
              명세서에서 정의를 찾지 못했어요{' '}
              {c.status.value !== 'confirmed' && <StatusTag status={c.status} detail={false} unverifiedText={COMPARE_UNVERIFIED_TEXT} />}
            </>
          )}
        </Row>
      </div>
    </div>
  )
}
