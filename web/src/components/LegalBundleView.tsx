import { Card, Descriptions, List, Space, Tag, Typography } from 'antd'
import { furtherReviewWhyLabel, reviewVerdictLabel, sourceKindLabel, speakerLabel } from '../labels'
import type { LegalEvidenceBundle, LegalSource } from '../types/generated/LegalEvidenceBundle'
import { HumanCheckTag } from './Marks'
import { StatusTag } from './StatusTag'

// 근거 하나: 자료 종류·식별자·판본·원문 위치 + 전문/요지 + 법원 판단/당사자 주장
function SourceItem({ s }: { s: LegalSource }) {
  return (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      <Space size={4} wrap>
        <Tag color="geekblue">{sourceKindLabel[s.source_kind]}</Tag>
        <Typography.Text strong>{s.identifier}</Typography.Text>
        {s.text_kind && <Tag>{s.text_kind === 'full' ? '전문' : '요지'}</Tag>}
        {s.speaker && <Tag>{speakerLabel[s.speaker]}</Tag>}
        <StatusTag status={s.status} />
      </Space>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        {/* 판본은 법령·심사기준에만 있다 (판례·심결은 원문 위치만) */}
        {s.source_kind === 'statute' || s.source_kind === 'guideline' ? `판본: ${s.evidence.edition ?? '모름'} · ` : ''}
        원문 위치: {s.evidence.location ?? '—'}
        {/* 판례·심결의 법원·선고일(심결일)은 알 때만 한 줄 */}
        {(s.court || s.decided_on) && ` · ${[s.court, s.decided_on].filter(Boolean).join(' ')}`}
      </Typography.Text>
      {s.evidence.raw_text && (
        <Typography.Text style={{ fontSize: 13 }}>
          “{s.evidence.raw_text}”
        </Typography.Text>
      )}
    </Space>
  )
}

// 법률 근거 묶음: 주장 번호마다 근거. "적용된다"는 판단은 하지 않는다 (근거와 상태만)
export function LegalBundleView({ b }: { b: LegalEvidenceBundle }) {
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="질문">{b.question.text}</Descriptions.Item>
        <Descriptions.Item label="기준 시점">{b.question.as_of ?? '현행'}</Descriptions.Item>
        <Descriptions.Item label="확인 기준일">{b.checked_on}</Descriptions.Item>
        <Descriptions.Item label="상태">
          <StatusTag status={b.status} />
        </Descriptions.Item>
      </Descriptions>
      {b.claims.map((c) => (
        <Card
          key={c.no}
          size="small"
          type="inner"
          title={<span style={{ whiteSpace: 'normal' }}>주장 {c.no}</span>}
          extra={<StatusTag status={c.status} />}
        >
          <Typography.Paragraph style={{ marginBottom: 8 }}>{c.text}</Typography.Paragraph>
          {c.flags.includes('needs_human_review') && (
            <div style={{ marginBottom: 8 }}>
              <HumanCheckTag>직접 검토 필요</HumanCheckTag>
            </div>
          )}
          {c.review ? (
            <Typography.Paragraph type="secondary" style={{ marginBottom: 8, fontSize: 13 }}>
              <Tag>{reviewVerdictLabel[c.review.verdict]}</Tag>
              {c.review.reason}
            </Typography.Paragraph>
          ) : (
            // 근거는 있는데 검토 결과가 없으면 "검토 안 함"을 드러낸다 (조용히 확인됨으로 보이지 않게)
            c.sources.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <Tag>검토 안 함</Tag>
              </div>
            )
          )}
          <List
            size="small"
            dataSource={c.sources}
            renderItem={(s) => (
              <List.Item style={{ paddingInline: 0 }}>
                <SourceItem s={s} />
              </List.Item>
            )}
          />
        </Card>
      ))}
      {b.claims.length === 0 && (
        <Typography.Text type="secondary">
          {b.unit_id === null ? '고른 자료 유형에서 근거를 찾지 못했습니다.' : '이 판단 단위의 근거 주장이 없습니다.'}
        </Typography.Text>
      )}
      <Card size="small" title="추가 검토할 자료">
        {b.further_review.length === 0 ? (
          <Typography.Text type="secondary">없음</Typography.Text>
        ) : (
          <ul style={{ margin: 0, paddingInlineStart: 18 }}>
            {b.further_review.map((x) => (
              <li key={x.chunk_id}>
                <Tag>{furtherReviewWhyLabel[x.why]}</Tag>
                {x.chunk_id}
                {x.note && ` — ${x.note}`}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </Space>
  )
}
