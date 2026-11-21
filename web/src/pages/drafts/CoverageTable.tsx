import { Table } from 'antd'
import type { Cell, CoverageModel } from './coverage'

// 칸 색: 대응함 검정 / 방향 안 고름 등 남음 갈색 / 직접 대응 빨강 (디자인 B 값)
const COLOR = { done: '#171719', pending: '#9c5800', manual: '#b00c0c' } as const

function CellView({ cell }: { cell: Cell | undefined }) {
  if (!cell) return <span style={{ color: '#37383c9c' }}>—</span>
  return <span style={{ color: COLOR[cell.kind], fontWeight: cell.kind === 'done' ? 400 : 600 }}>{cell.text}</span>
}

// 거절이유 × 청구항 표: 행 = 청구항, 열 = 거절이유. 좁은 화면에서는 표 안에서만 가로로 민다
export function CoverageTable({ model }: { model: CoverageModel }) {
  const left = model.total - model.done
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 className="heading2" style={{ flex: '1 1 auto', margin: 0 }}>
          대응 현황 · 거절이유 × 청구항
        </h2>
        <span className="label1 t3">{`${model.total}칸 중 ${model.done}칸 대응 · ${left}칸 남음`}</span>
      </div>
      <Table
        size="small"
        bordered
        pagination={false}
        scroll={{ x: 'max-content' }}
        rowKey="claim"
        dataSource={model.rows}
        columns={[
          { title: '청구항', dataIndex: 'claim', width: 90 },
          ...model.cols.map((c) => ({
            title: c.label,
            key: `r${c.no}`,
            width: 200,
            render: (_: unknown, row: CoverageModel['rows'][number]) => <CellView cell={row.cells[c.no]} />,
          })),
        ]}
      />
      <span className="label2 t3">"대응함"은 초안에 대응을 적었다는 뜻이에요. 거절이유가 풀렸다는 판정이 아니에요.</span>
    </div>
  )
}
