import { Badge, Card, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useLoaderData, useNavigate } from 'react-router'
import { StatusTag } from '../components/StatusTag'
import { dateTimeText } from '../format'
import { noticeKindLabel, rejectionKindLabel, runStateLabel } from '../labels'
import type { CaseSummary, RunState } from '../types/provisional/case'

// 진행 상태 → 점 색
const runBadge: Record<RunState, 'success' | 'processing' | 'warning' | 'error' | 'default'> = {
  queued: 'default',
  running: 'processing',
  waiting_for_human: 'warning',
  succeeded: 'success',
  failed: 'error',
  cancelled: 'default',
}

const columns: ColumnsType<CaseSummary> = [
  { title: '사건 이름', dataIndex: 'case_name', render: (v: string) => <Typography.Text strong>{v}</Typography.Text> },
  { title: '출원번호', dataIndex: 'application_number', render: (v: string | null) => v ?? '—' },
  {
    title: '최근 통지 종류',
    render: (_, c) => (c.latest_oa.notice_kind ? noticeKindLabel[c.latest_oa.notice_kind] : '—'),
  },
  {
    title: '거절이유 종류',
    render: (_, c) => (
      <Space size={[0, 4]} wrap>
        {c.rejection_kinds.map((k) => (
          <Tag key={k}>{rejectionKindLabel[k]}</Tag>
        ))}
      </Space>
    ),
  },
  {
    title: '진행 상태',
    dataIndex: 'run_state',
    render: (v: RunState) => <Badge status={runBadge[v]} text={runStateLabel[v]} />,
  },
  { title: '결과 상태', dataIndex: 'status', render: (v: CaseSummary['status']) => <StatusTag status={v} /> },
  {
    title: '검토할 사항',
    dataIndex: 'review_items_count',
    align: 'right',
    // 모르면 "모름" (0건 "없음"과 구분)
    render: (n: number | null) =>
      n === null ? '모름' : n > 0 ? <Typography.Text strong>{n}건</Typography.Text> : '없음',
  },
  { title: '마지막으로 연 때', dataIndex: 'last_opened_at', render: dateTimeText },
]

// 사건 목록: 사건 표. 통지서 올리기는 머리 막대 버튼(/cases/new). 줄을 누르면 사건 작업대
export function CaseListPage() {
  const cases = useLoaderData() as CaseSummary[]
  const navigate = useNavigate()

  return (
    <main style={{ maxWidth: 1120, margin: '0 auto', padding: '40px 32px 80px' }}>
      <Card size="small" title={`사건 ${cases.length}건`}>
        <Table<CaseSummary>
          rowKey="case_id"
          size="middle"
          columns={columns}
          dataSource={cases}
          pagination={false}
          scroll={{ x: 900 }}
          locale={{ emptyText: '아직 사건이 없습니다. 위 "통지서 올리기"로 시작해 주세요.' }}
          onRow={(c) => ({
            onClick: () => navigate(`/oas/${c.latest_oa.oa_id}`),
            style: { cursor: 'pointer' },
          })}
        />
      </Card>
    </main>
  )
}
