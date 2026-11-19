import { UploadOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Space, Table, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { HumanCheckTag } from '../../components/Marks'
import { StatusTag } from '../../components/StatusTag'
import { lookupResultLabel, materialKindLabel, sourceLabel } from '../../labels'
import type { CaseMaterials, LookupResult } from '../../types/generated/CaseMaterials'
import type { OAResult } from '../../types/generated/OAResult'

// 사건 자료 표의 한 줄: 받은 자료와 빠진 자료를 한 표에
interface Row {
  key: string
  what: string
  edition: string
  how: string
  lookup: LookupResult | null // 빠진 자료면 조회 결과, 받은 자료면 null
  askUpload: boolean
}

function rowsOf(m: CaseMaterials, r: OAResult): Row[] {
  const got: Row[] = m.documents.map((d) => ({
    key: d.document_id,
    what: materialKindLabel[d.kind] ?? d.kind,
    // 판은 어느 시점 문서인지: 통지서는 발송번호로 묶는다 (날짜만으로 합치지 않음)
    edition: d.kind === 'oa' ? `발송번호 ${r.dispatch_number.raw_text ?? r.dispatch_number.value ?? '모름'}` : '—',
    how: sourceLabel[d.source] ?? d.source,
    lookup: null,
    askUpload: false,
  }))
  const missing: Row[] = m.missing.map((x, i) => ({
    key: `missing-${i}`,
    what: x.what,
    edition: '판 모름', // 공개공보·등록공보는 다른 판이라 데이터에 없으면 짐작하지 않는다
    how: '자동 조회',
    lookup: x.lookup_result,
    askUpload: x.ask_upload,
  }))
  return [...got, ...missing]
}

// 사건 자료 표 + 보류한 작업 한 줄
export function MaterialsCard({ m, r }: { m: CaseMaterials; r: OAResult }) {
  const { message } = App.useApp()

  const columns: ColumnsType<Row> = [
    { title: '자료', dataIndex: 'what' },
    { title: '판', dataIndex: 'edition' },
    { title: '가져온 방법', dataIndex: 'how' },
    {
      title: '상태',
      render: (_, row) => {
        if (row.lookup === null) return <Typography.Text>받음</Typography.Text>
        // 지원 안 하는 나라는 "올려 주세요"가 아니라 "직접 확인"
        if (row.lookup === 'unsupported_country') return <HumanCheckTag>지원 안 하는 나라 · 직접 확인</HumanCheckTag>
        return (
          <StatusTag
            status={{ value: 'unverified', reason: row.lookup, checked: null, searched_scope: null }}
          />
        )
      },
    },
    {
      title: '할 일',
      render: (_, row) =>
        row.askUpload ? (
          <Button
            size="small"
            icon={<UploadOutlined />}
            onClick={() => message.info('자료 올리기(POST /cases/{id}/documents)는 서버 연결 뒤 동작합니다')}
          >
            올려 주세요
          </Button>
        ) : null,
    },
  ]

  return (
    <Card size="small" title="사건 자료" id="materials">
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Table<Row>
          size="small"
          rowKey="key"
          columns={columns}
          dataSource={rowsOf(m, r)}
          pagination={false}
          scroll={{ x: 640 }}
        />
        {m.held_tasks.length > 0 && (
          <Alert
            type="info"
            showIcon
            message={`보류한 작업 ${m.held_tasks.length}건: ${m.held_tasks
              .map((h) => `${h.task} (기다리는 자료: ${h.waiting_for})`)
              .join(' · ')}`}
          />
        )}
        {m.missing.some((x) => x.lookup_result !== 'unsupported_country') && (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            빠진 자료: {[...new Set(m.missing.map((x) => lookupResultLabel[x.lookup_result]))].join(', ')}. 나머지 작업은
            진행합니다.
          </Typography.Text>
        )}
      </Space>
    </Card>
  )
}
