import {
  ArrowRightOutlined,
  AuditOutlined,
  CheckOutlined,
  DiffOutlined,
  EllipsisOutlined,
  RobotOutlined,
} from '@ant-design/icons'
import { Card, Col, Row, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { HumanCheckTag } from '../../components/Marks'
import { StatusTag } from '../../components/StatusTag'
import type { ReactNode } from 'react'
import type {
  ComparisonRow,
  ComparisonTable,
  InventiveSummary,
  Judgment,
  NoveltySummary,
} from '../../types/generated/ComparisonTable'

// 판단 값 (상태 네 가지와 다른 축). 색만으로 나누지 않게 아이콘도 붙인다
const judgmentTag: Record<Judgment, { color: string; text: string; icon: ReactNode }> = {
  disclosed: { color: 'green', text: '개시됨', icon: <CheckOutlined /> },
  difference_candidate: { color: 'orange', text: '차이 후보', icon: <DiffOutlined /> },
  unclear: { color: 'default', text: '불명', icon: <EllipsisOutlined /> },
}

const columns: ColumnsType<ComparisonRow> = [
  { title: '청구항', render: (_, r) => `청구항 ${r.claim}` }, // OA 시점 청구항 번호
  {
    title: '구성요소',
    render: (_, r) => (
      <Space direction="vertical" size={0}>
        <span>{r.element}</span>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {r.element_location}
        </Typography.Text>
      </Space>
    ),
  },
  { title: '인용문헌', dataIndex: 'citation' },
  {
    // 인용문헌 위치(식별번호·도면 번호)는 줄의 근거 evidence[].location
    title: '위치',
    render: (_, r) => r.evidence.map((e) => e.location).filter(Boolean).join(', ') || '—',
  },
  {
    title: '판단',
    render: (_, r) => (
      <Tag color={judgmentTag[r.judgment].color} icon={judgmentTag[r.judgment].icon}>
        {judgmentTag[r.judgment].text}
      </Tag>
    ),
  },
  { title: '상태', render: (_, r) => <StatusTag status={r.status} /> },
  {
    // 심사관이 짚은 문단과 AI가 새로 찾은 문단은 이 열로만 구분한다
    title: '문단 출처',
    render: (_, r) =>
      r.paragraph_source === 'examiner' ? (
        <Tag icon={<AuditOutlined />}>심사관 지정</Tag>
      ) : (
        <Tag icon={<RobotOutlined />} color="purple">
          AI가 새로 찾음
        </Tag>
      ),
  },
  {
    title: '왜 가져왔나',
    width: 260,
    render: (_, r) => <Typography.Text type="secondary">{r.why_retrieved ?? '—'}</Typography.Text>,
  },
]

// 진보성: 차이점 → 결합 → 효과 후보 순
function InventiveSteps({ s }: { s: InventiveSummary }) {
  const box = (title: string, body: ReactNode) => (
    <Card size="small" title={title} style={{ height: '100%' }}>
      {body}
    </Card>
  )
  const list = (xs: string[]) =>
    xs.length === 0 ? (
      <Typography.Text type="secondary">없음</Typography.Text>
    ) : (
      <ul style={{ margin: 0, paddingInlineStart: 18 }}>
        {xs.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
    )
  return (
    <Row gutter={[8, 8]} align="stretch">
      <Col xs={24} md={7}>{box('1 차이점', list(s.differences))}</Col>
      <Col xs={0} md={1} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <ArrowRightOutlined />
      </Col>
      <Col xs={24} md={7}>{box('2 결합', s.combination)}</Col>
      <Col xs={0} md={1} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <ArrowRightOutlined />
      </Col>
      <Col xs={24} md={8}>{box('3 효과 후보', list(s.effect_candidates))}</Col>
    </Row>
  )
}

// 신규성 요약 판정: 표의 판단과 같은 색 (차이 없음·실질적 동일 = 개시됨 쪽 초록, 차이 있음 = 차이 후보 쪽 주황)
const noveltyVerdict = {
  no_difference: { text: '차이 없음', color: 'green', icon: <CheckOutlined /> },
  substantially_same_candidate: { text: '실질적 동일 후보', color: 'lime', icon: <EllipsisOutlined /> },
  different: { text: '차이 있음', color: 'orange', icon: <DiffOutlined /> },
}

// 신규성: 인용 하나와만 대비한다
function NoveltyLine({ s }: { s: NoveltySummary }) {
  return (
    <Card size="small" title={`신규성 대비: ${s.citation} 하나와만`}>
      <Space wrap>
        <Tag color={noveltyVerdict[s.verdict].color} icon={noveltyVerdict[s.verdict].icon}>
          {noveltyVerdict[s.verdict].text}
        </Tag>
        <Typography.Text>{s.reason}</Typography.Text>
      </Space>
    </Card>
  )
}

// 구성 대비: 인용문헌마다 대비 여부 → 요약 → 대비 표
export function ComparisonView({ t }: { t: ComparisonTable }) {
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Space size={6} wrap>
        <Typography.Text type="secondary">인용문헌:</Typography.Text>
        {t.citations.map((c) =>
          c.compared ? (
            <Tag key={c.label} color="blue">
              {c.label} {c.number} · 대비함
            </Tag>
          ) : (
            <Space key={c.label} size={2}>
              <Tag>
                {c.label} {c.number}
              </Tag>
              {c.skipped_status && <StatusTag status={c.skipped_status} />}
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {c.skipped_reason}
              </Typography.Text>
            </Space>
          ),
        )}
      </Space>
      {/* 대비하지 않은 인용문헌이 있으면 직접 검토 (상태가 아니라 flags로 알린다) */}
      {t.flags.includes('needs_human_review') && <HumanCheckTag>직접 검토 필요</HumanCheckTag>}
      {t.summary.kind === 'inventive_step' ? <InventiveSteps s={t.summary} /> : <NoveltyLine s={t.summary} />}
      <Table<ComparisonRow>
        size="small"
        rowKey={(r, i) => `${r.claim}-${r.element_location}-${r.citation}-${i}`}
        columns={columns}
        dataSource={t.rows}
        pagination={false}
        scroll={{ x: 900 }}
        locale={{ emptyText: '대비한 줄이 없습니다 (인용문헌 본문을 받으면 대비)' }}
      />
    </Space>
  )
}
