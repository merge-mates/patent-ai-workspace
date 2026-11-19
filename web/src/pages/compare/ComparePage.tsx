import { BookOutlined } from '@ant-design/icons'
import { Alert, Badge, Button, Card, Descriptions, Drawer, Empty, Radio, Space, Typography } from 'antd'
import { useState } from 'react'
import { useLoaderData, useRouteLoaderData, useSearchParams } from 'react-router'
import { LegalBundleView } from '../../components/LegalBundleView'
import { AiResultMark, ExampleDataMark, HumanCheckTag } from '../../components/Marks'
import { StatusTag } from '../../components/StatusTag'
import { claimRange } from '../../format'
import { articleLabel, rejectionKindLabel } from '../../labels'
import type { CompareLoaderData, OALoaderData } from '../../loaders'
import type { JudgmentUnit } from '../../types/provisional/analysis'
import { ClarityView } from './ClarityView'
import { ComparisonView } from './ComparisonView'

const unitLabel = (u: JudgmentUnit) =>
  `${u.order} · 거절이유 ${u.rejection} ${rejectionKindLabel[u.rejection_kind]} · ${
    u.unit_kind === 'single_claim' ? `청구항 ${u.representative_claim}` : `청구항 ${u.representative_claim} 묶음`
  }`

// 3 대비와 근거: 판단 단위(묶음)를 고르면 그 묶음의 대비표(또는 명확성 검토)와 법률 근거를 본다
export function ComparePage() {
  const { units, comparisons, clarity, legal } = useLoaderData() as CompareLoaderData
  const { oaResult } = useRouteLoaderData('oa') as OALoaderData
  // 고른 묶음은 주소(?unit=)에 둔다: 새로고침·다시 열기 뒤에도 같은 묶음
  const [params, setParams] = useSearchParams()
  const [legalOpen, setLegalOpen] = useState(false)

  const unit = units.find((u) => u.unit_id === params.get('unit')) ?? units[0]
  const unsupported = oaResult?.result.rejections.filter((r) => !r.supported) ?? []

  if (!unit) {
    return (
      <Card size="small" title="대비와 근거">
        <Empty description="판단 단위가 없습니다" />
      </Card>
    )
  }
  const table = comparisons.find((t) => t.unit_id === unit.unit_id)
  const review = clarity.find((c) => c.unit_id === unit.unit_id)
  const bundle = legal.find((b) => b.unit_id === unit.unit_id)

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {unsupported.map((r) => (
        <Alert
          key={r.no}
          type="warning"
          showIcon
          message={
            <Space wrap>
              거절이유 {r.no}(특허법 {articleLabel(r.article.value)})는 AI가 다루지 않아 판단 단위가 없습니다.
              <HumanCheckTag>직접 검토 필요</HumanCheckTag>
            </Space>
          }
        />
      ))}
      <Card
        size="small"
        title={
          <Space>
            판단 단위 <ExampleDataMark />
          </Space>
        }
      >
        <Radio.Group
          optionType="button"
          value={unit.unit_id}
          onChange={(e) => setParams({ unit: e.target.value as string })}
          options={units.map((u) => ({ label: unitLabel(u), value: u.unit_id }))}
          style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}
        />
      </Card>
      <Card
        size="small"
        title={
          <Space wrap>
            {unit.rejection_kind === 'clarity' ? '명확성 문구 검토' : '구성 대비'} <AiResultMark /> <ExampleDataMark />
          </Space>
        }
        extra={
          <Badge count={bundle?.claims.length ?? 0} size="small" color="#1677FF">
            <Button size="small" icon={<BookOutlined />} onClick={() => setLegalOpen(true)}>
              법률 근거
            </Button>
          </Badge>
        }
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Descriptions size="small" column={{ xs: 1, sm: 1, md: 3, lg: 3, xl: 3, xxl: 3 }}>
            <Descriptions.Item label="묶음">
              {unit.unit_kind === 'single_claim' ? '청구항 하나' : '독립항 묶음'}
            </Descriptions.Item>
            <Descriptions.Item label="청구항">{claimRange(unit.claims)}</Descriptions.Item>
            {unit.read_with.length > 0 && (
              <Descriptions.Item label="함께 읽을 청구항">{claimRange(unit.read_with)}</Descriptions.Item>
            )}
            <Descriptions.Item label="상태">
              <StatusTag status={unit.status} />
            </Descriptions.Item>
          </Descriptions>
          {table && <ComparisonView t={table} />}
          {review && <ClarityView c={review} />}
          {!table && !review && <Empty description="이 묶음의 대비 결과가 아직 없습니다" />}
        </Space>
      </Card>
      <Drawer
        title={
          <Space>
            법률 근거 <AiResultMark /> <ExampleDataMark />
          </Space>
        }
        open={legalOpen}
        onClose={() => setLegalOpen(false)}
        width={560}
      >
        {bundle ? (
          <LegalBundleView b={bundle} />
        ) : (
          <Typography.Text type="secondary">이 판단 단위의 법률 근거가 아직 없습니다.</Typography.Text>
        )}
      </Drawer>
    </Space>
  )
}
