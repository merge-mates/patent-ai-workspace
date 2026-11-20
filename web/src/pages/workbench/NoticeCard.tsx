import { Card, Descriptions, Space } from 'antd'
import { AiResultMark, HumanCheckTag } from '../../components/Marks'
import { FieldValue } from '../../components/FieldValue'
import { StatusTag } from '../../components/StatusTag'
import { claimsText } from '../../format'
import { noticeKindLabel } from '../../labels'
import type { OAResult } from '../../types/generated/OAResult'

// 통지 정보: 출원번호·발송번호·통지 종류·심사 대상 청구항·통지일·제출기일
// 번호는 원문 글자 그대로 보인다 (정규화 값은 원문이 없을 때만).
// 날짜·기한은 AI가 확정하지 않는다: 원문 글자만 보이고 "직접 확인"
export function NoticeCard({ r }: { r: OAResult }) {
  const kind = r.notice_kind
  return (
    <Card
      size="small"
      title={
        <Space>
          통지 정보 <AiResultMark />
        </Space>
      }
      extra={<StatusTag status={r.status} />}
    >
      <Descriptions size="small" column={{ xs: 1, sm: 1, md: 2, lg: 2, xl: 2, xxl: 2 }} bordered>
        <Descriptions.Item label="출원번호">
          <FieldValue v={r.application_number}>{r.application_number.raw_text ?? r.application_number.value ?? '—'}</FieldValue>
        </Descriptions.Item>
        <Descriptions.Item label="발송번호">
          <FieldValue v={r.dispatch_number}>{r.dispatch_number.raw_text ?? r.dispatch_number.value ?? '—'}</FieldValue>
        </Descriptions.Item>
        <Descriptions.Item label="통지 종류">
          <FieldValue v={kind}>{kind.value ? noticeKindLabel[kind.value] : (kind.raw_text ?? '—')}</FieldValue>
        </Descriptions.Item>
        <Descriptions.Item label="심사 대상 청구항">
          <FieldValue v={r.examined_claims}>{claimsText(r.examined_claims)}</FieldValue>
        </Descriptions.Item>
        <Descriptions.Item label="통지일">
          <FieldValue v={r.notice_date}>
            {r.notice_date.raw_text ?? '—'} <HumanCheckTag />
          </FieldValue>
        </Descriptions.Item>
        <Descriptions.Item label="제출기일">
          <FieldValue v={r.response_due}>
            {r.response_due.raw_text ?? '—'} <HumanCheckTag />
          </FieldValue>
        </Descriptions.Item>
      </Descriptions>
    </Card>
  )
}
