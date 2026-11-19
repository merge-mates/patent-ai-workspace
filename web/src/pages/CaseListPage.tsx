import { InboxOutlined } from '@ant-design/icons'
import { App, Badge, Card, Space, Table, Tag, Typography, Upload } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useLoaderData, useNavigate } from 'react-router'
import { api, API_MODE } from '../api'
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
    render: (n: number) => (n > 0 ? <Typography.Text strong>{n}건</Typography.Text> : '없음'),
  },
  { title: '마지막으로 연 때', dataIndex: 'last_opened_at', render: dateTimeText },
]

// 사건 목록: 맨 위 통지서 올리기, 아래 사건 표. 줄을 누르면 사건 작업대
export function CaseListPage() {
  const cases = useLoaderData() as CaseSummary[]
  const navigate = useNavigate()
  const { message } = App.useApp()

  // 통지서 PDF를 올리면 사건·OA를 만들고 작업대로 간다 (mock은 예시 사건을 연다)
  const upload = async (file: File) => {
    try {
      const created = await api.createCase(file)
      message.success(
        API_MODE === 'mock' ? `${file.name}: mock이라 예시 사건을 엽니다` : `${file.name}을 올렸습니다`,
      )
      navigate(`/oas/${created.oa_id}`)
    } catch (e) {
      message.error(`올리지 못했습니다: ${e instanceof Error ? e.message : String(e)}`)
    }
    return false // antd가 따로 업로드하지 않게
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card size="small">
        <Upload.Dragger accept="application/pdf,.pdf" showUploadList={false} beforeUpload={upload}>
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">의견제출통지서 PDF 올리기</p>
          <p className="ant-upload-hint">
            새 사건을 만들고 거절이유별로 정리합니다. 같은 사건의 다음 통지서는 사건 안에서 올립니다.
          </p>
        </Upload.Dragger>
      </Card>
      <Card size="small" title={`사건 ${cases.length}건`}>
        <Table<CaseSummary>
          rowKey="case_id"
          size="middle"
          columns={columns}
          dataSource={cases}
          pagination={false}
          scroll={{ x: 900 }}
          locale={{ emptyText: '아직 사건이 없습니다. 위에서 통지서를 올려 주세요.' }}
          onRow={(c) => ({
            onClick: () => navigate(`/oas/${c.latest_oa.oa_id}`),
            style: { cursor: 'pointer' },
          })}
        />
      </Card>
    </Space>
  )
}
