import { Card, Descriptions, List, Space, Tag, Typography } from 'antd'
import { sourceKindLabel } from '../labels'
import type { LegalEvidenceBundle, LegalSource } from '../types/provisional/analysis'
import { StatusTag } from './StatusTag'

// 근거 하나: 자료 종류·식별자·판본·원문 위치 + 전문/요지 + 법원 판단/당사자 주장
function SourceItem({ s }: { s: LegalSource }) {
  return (
    <Space direction="vertical" size={2} style={{ width: '100%' }}>
      <Space size={4} wrap>
        <Tag color="geekblue">{sourceKindLabel[s.source_kind]}</Tag>
        <Typography.Text strong>{s.identifier}</Typography.Text>
        <Tag>{s.text_kind === 'full' ? (s.source_kind === 'precedent' ? '판례 전문' : '원문') : '요지'}</Tag>
        {s.speaker && <Tag>{s.speaker === 'court' ? '법원 판단' : '당사자 주장'}</Tag>}
        <StatusTag status={s.status} />
      </Space>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        판본: {s.edition ?? '모름'} · 원문 위치: {s.location}
      </Typography.Text>
      {s.excerpt !== '—' && (
        <Typography.Text style={{ fontSize: 13 }}>
          “{s.excerpt}”
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
        <Descriptions.Item label="질문">{b.question}</Descriptions.Item>
        <Descriptions.Item label="기준 시점">{b.as_of ?? '현행'}</Descriptions.Item>
        <Descriptions.Item label="확인 기준일">{b.checked_on}</Descriptions.Item>
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
        <Typography.Text type="secondary">고른 자료 유형에서 근거를 찾지 못했습니다.</Typography.Text>
      )}
      <Card size="small" title="추가 검토할 자료">
        {b.further_review.length === 0 ? (
          <Typography.Text type="secondary">없음</Typography.Text>
        ) : (
          <ul style={{ margin: 0, paddingInlineStart: 18 }}>
            {b.further_review.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        )}
      </Card>
    </Space>
  )
}
