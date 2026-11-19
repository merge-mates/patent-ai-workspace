import { Alert, Card, Descriptions, Empty, Segmented, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { FieldValue } from '../../components/FieldValue'
import { AiResultMark, HumanCheckTag } from '../../components/Marks'
import { SourceLink } from '../../components/SourceLink'
import { StatusTag } from '../../components/StatusTag'
import { claimsText } from '../../format'
import { articleLabel, rejectionKindLabel } from '../../labels'
import type { ClaimRow, OAResult, Rejection } from '../../types/generated/OAResult'

// 거절이유가 어떤 방식으로 다뤄지나: 문헌과 대조 / 문장을 검토 / AI가 다루지 않음
function TypeTag({ rej }: { rej: Rejection }) {
  if (!rej.supported) return <Tag color="default">지원 안 함</Tag>
  if (rej.kind === 'clarity') return <Tag color="cyan">문장 검토형</Tag>
  return <Tag color="geekblue">문헌 대조형</Tag>
}

// "claim:3" → "청구항 3", "rejection:1" → "거절이유 1"
const sameAsText = (s: string) =>
  s.replace(/^claim:(\d+)$/, '청구항 $1').replace(/^rejection:(\d+)$/, '거절이유 $1')

function locationText(row: ClaimRow): string {
  if (row.no_location) return row.no_location
  const parts = Object.entries(row.locations).map(([label, locs]) => `${label} ${locs.join(', ')}`)
  return parts.length > 0 ? parts.join(' / ') : '—'
}

// 청구항 줄 표의 열 (거절이유별·청구항별 둘이 같이 쓴다)
const rowColumns = (clarity: boolean): ColumnsType<ClaimRow> => [
  ...(clarity
    ? [
        {
          title: '문제 표현',
          render: (_: unknown, row: ClaimRow) =>
            row.clarity_terms.length > 0 ? row.clarity_terms.map((t) => `'${t}'`).join(', ') : '—',
        },
        {
          title: '이유 (AI 참고)',
          render: (_: unknown, row: ClaimRow) => (
            <Typography.Text type="secondary">{row.clarity_reason ?? '—'}</Typography.Text>
          ),
        },
      ]
    : [
        { title: '인용', render: (_: unknown, row: ClaimRow) => (row.citations.length ? row.citations.join(' + ') : '—') },
        { title: '인용 위치', render: (_: unknown, row: ClaimRow) => locationText(row) },
      ]),
  {
    title: '같은 취지',
    render: (_, row) => (row.same_as.length ? row.same_as.map(sameAsText).join(', ') : '—'),
  },
  { title: '상태', render: (_, row) => <StatusTag status={row.status} /> },
  { title: '원문', render: (_, row) => <SourceLink page={row.page} rawText={row.raw_text} /> },
]

function RejectionItem({ rej, rows }: { rej: Rejection; rows: ClaimRow[] }) {
  return (
    <Card
      type="inner"
      size="small"
      title={
        <Space size={6} wrap>
          <span>
            거절이유 {rej.no} · {rejectionKindLabel[rej.kind]}
          </span>
          <Typography.Text type="secondary">특허법 {articleLabel(rej.article.value)}</Typography.Text>
          <TypeTag rej={rej} />
        </Space>
      }
      extra={<StatusTag status={rej.status} />}
    >
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        {!rej.supported && (
          <Alert
            type="warning"
            showIcon
            message={
              <Space wrap>
                AI가 다루지 않는 거절이유입니다. 정리·대비·초안을 만들지 않습니다.
                <HumanCheckTag>직접 검토 필요</HumanCheckTag>
              </Space>
            }
          />
        )}
        <Descriptions size="small" column={1} bordered>
          <Descriptions.Item label="조문">
            <FieldValue v={rej.article}>{rej.article.raw_text ?? articleLabel(rej.article.value)}</FieldValue>
          </Descriptions.Item>
          <Descriptions.Item label="대상 청구항">
            <FieldValue v={rej.claims}>{claimsText(rej.claims)}</FieldValue>
          </Descriptions.Item>
          {rej.citations.length > 0 && (
            <Descriptions.Item label="인용문헌·인용 위치">
              <Space direction="vertical" size={6}>
                {rej.citations.map((c) => (
                  <Space key={c.label} size={6} wrap align="start">
                    <Tag>{c.label}</Tag>
                    <FieldValue v={c.number}>{c.number.value ?? c.number.raw_text ?? '번호 모름'}</FieldValue>
                    {!c.country_supported && <HumanCheckTag>지원 안 하는 나라 · 직접 확인</HumanCheckTag>}
                    <FieldValue v={c.cited_paragraphs}>
                      {c.cited_paragraphs.value?.join(', ') ?? c.cited_paragraphs.raw_text ?? '위치 없음'}
                    </FieldValue>
                  </Space>
                ))}
              </Space>
            </Descriptions.Item>
          )}
          <Descriptions.Item label="심사관 논리 요지">
            <FieldValue v={rej.examiner_reasoning}>
              {rej.examiner_reasoning.value ?? rej.examiner_reasoning.raw_text ?? '—'}
            </FieldValue>
          </Descriptions.Item>
        </Descriptions>
        {rej.supported && (
          <Table<ClaimRow>
            size="small"
            rowKey={(row, i) => `${row.claim}-${row.rejection}-${i}`}
            columns={[
              { title: '청구항', render: (_, row) => (row.claim === null ? '모름' : `제${row.claim}항`) },
              ...rowColumns(rej.kind === 'clarity'),
            ]}
            dataSource={rows}
            pagination={false}
            scroll={{ x: 640 }}
            locale={{ emptyText: '청구항 줄 없음' }}
          />
        )}
      </Space>
    </Card>
  )
}

// 청구항별: 청구항 하나에 걸린 거절이유를 모아 본다 (청구항 칸은 합침)
function ByClaim({ r }: { r: OAResult }) {
  const byNo = new Map(r.rejections.map((x) => [x.no, x]))
  const rows = [...r.claim_rows].sort(
    (a, b) => (a.claim ?? 9999) - (b.claim ?? 9999) || (a.rejection ?? 0) - (b.rejection ?? 0),
  )
  // 같은 청구항 줄의 개수: 첫 줄만 그만큼 합친다
  const span = rows.map((row, i) => {
    if (i > 0 && rows[i - 1].claim === row.claim) return 0
    let n = 1
    while (rows[i + n]?.claim === row.claim) n++
    return n
  })
  const columns: ColumnsType<ClaimRow> = [
    {
      title: '청구항',
      render: (_, row) => (row.claim === null ? '모름' : `제${row.claim}항`),
      onCell: (_, i) => ({ rowSpan: span[i ?? 0] }),
    },
    {
      title: '거절이유',
      render: (_, row) => {
        const rej = row.rejection === null ? undefined : byNo.get(row.rejection)
        return rej ? `${rej.no} · ${rejectionKindLabel[rej.kind]}` : '모름'
      },
    },
    {
      title: '인용·위치 / 문제 표현',
      render: (_, row) =>
        row.clarity_terms.length > 0
          ? row.clarity_terms.map((t) => `'${t}'`).join(', ')
          : `${row.citations.join(' + ') || '—'} ${locationText(row) === '—' ? '' : `· ${locationText(row)}`}`,
    },
    ...rowColumns(false).slice(2),
  ]
  if (rows.length === 0) return <Empty description="청구항 줄이 없습니다" />
  return (
    <Table<ClaimRow>
      size="small"
      rowKey={(row, i) => `${row.claim}-${row.rejection}-${i}`}
      columns={columns}
      dataSource={rows}
      pagination={false}
      bordered
      scroll={{ x: 640 }}
    />
  )
}

// 거절이유 정리: 거절이유별 카드 / 청구항별 표
export function RejectionsCard({ r }: { r: OAResult }) {
  const [view, setView] = useState<'rejection' | 'claim'>('rejection')
  const unsupported = r.rejections.filter((x) => !x.supported).length
  return (
    <Card
      size="small"
      id="rejections"
      title={
        <Space>
          거절이유 정리 <AiResultMark />
        </Space>
      }
      extra={
        <Segmented
          size="small"
          value={view}
          onChange={(v) => setView(v as 'rejection' | 'claim')}
          options={[
            { label: '거절이유별', value: 'rejection' },
            { label: '청구항별', value: 'claim' },
          ]}
        />
      }
    >
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Typography.Text type="secondary">
          거절이유 {r.rejections.length}개
          {unsupported > 0 ? ` (AI가 다루지 않는 것 ${unsupported}개 포함)` : ''} · 청구항 줄 {r.claim_rows.length}개
        </Typography.Text>
        {r.rejections.length === 0 && <Empty description="거절이유를 찾지 못했습니다 (확인되지 않음)" />}
        {view === 'rejection'
          ? r.rejections.map((rej) => (
              <RejectionItem key={rej.no} rej={rej} rows={r.claim_rows.filter((row) => row.rejection === rej.no)} />
            ))
          : <ByClaim r={r} />}
      </Space>
    </Card>
  )
}
