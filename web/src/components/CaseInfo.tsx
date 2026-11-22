import { Button, Typography } from 'antd'
import { useContext } from 'react'
import { claimsText } from '../format'
import { HUMAN_ENTERED_CHECKED, noticeKindLabel } from '../labels'
import type { OAResult } from '../types/generated/OAResult'
import { type Extracted, candidatesText } from './extracted'
import { AiResultMark, HumanCheckTag, HumanTag } from './Marks'
import { SourceContext } from './sourceContext'
import { StatusTag } from './StatusTag'

// 사건 정보 한 칸: 이름 · 값(원문 글자) · 상태 꼬리표(확인됨은 없음) · "통지서 N쪽"
// 날짜·기한은 AI가 확정하지 않는다: 원문 글자 + "직접 확인"
function InfoField({ label, value, v, human = false }: { label: string; value: string; v: Extracted; human?: boolean }) {
  const { openPage } = useContext(SourceContext)
  const confirmed = v.status.value === 'confirmed'
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      <span className="label1 t3">{label}</span>
      <span className="label1" style={{ fontWeight: 600 }}>
        {value}
      </span>
      {/* 확인됨은 작은 체크(마우스를 올리면 무엇을 확인했나), 그 밖은 꼬리표. 쪽이 없어도 상태는 보인다 */}
      <StatusTag status={v.status} compact />
      {human && <HumanCheckTag />}
      {/* 사람이 직접 넣은 번호는 AI가 읽은 값과 구분해 "직접 입력" 꼬리표 */}
      {v.status.checked === HUMAN_ENTERED_CHECKED && <HumanTag>직접 입력</HumanTag>}
      {v.page !== null && (
        // 확인된 값만 "통지서 N쪽", 아니면 "후보 위치" (F5: 원문 링크는 확인된 값만)
        <Button type="link" size="small" onClick={() => openPage(v.page, v.raw_text)}>
          {confirmed ? `통지서 ${v.page}쪽` : `후보 위치 ${v.page}쪽`}
        </Button>
      )}
      {/* 충돌이면 두 후보를 나란히 보인다 (AI가 하나를 고르지 않음) */}
      {v.candidates.length > 0 && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          후보: {candidatesText(v)}
        </Typography.Text>
      )}
    </div>
  )
}

// 사건 정보(펼침): 지금까지 통지 정보 카드가 하던 일 (값 · 상태 · 원문 쪽)
export function CaseInfo({ r }: { r: OAResult }) {
  const kind = r.notice_kind
  const allowable = r.examiner_hints.allowable_claims
  return (
    <div style={{ display: 'flex', gap: '8px 32px', flexWrap: 'wrap', padding: '8px 0 4px', alignItems: 'center' }}>
      <AiResultMark />
      <InfoField label="출원번호" value={r.application_number.raw_text ?? r.application_number.value ?? '—'} v={r.application_number} />
      <InfoField label="발송번호" value={r.dispatch_number.raw_text ?? r.dispatch_number.value ?? '—'} v={r.dispatch_number} />
      <InfoField label="통지일" value={r.notice_date.raw_text ?? '—'} v={r.notice_date} human />
      <InfoField label="제출기일" value={r.response_due.raw_text ?? '—'} v={r.response_due} human />
      <InfoField label="통지 종류" value={kind.value ? noticeKindLabel[kind.value] : (kind.raw_text ?? '—')} v={kind} />
      <InfoField label="심사 대상 청구항" value={claimsText(r.examined_claims)} v={r.examined_claims} />
      <InfoField label="특허 가능한 청구항" value={claimsText(allowable)} v={allowable} />
    </div>
  )
}
