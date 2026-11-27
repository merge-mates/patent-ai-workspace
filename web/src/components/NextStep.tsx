import { Tag } from 'antd'
import type { ReactNode } from 'react'

// "다음 단계" 안내 한 줄: 아직 만들지 않은 기능이 들어갈 자리와 그 모습을 글로만 보인다.
// 값은 지어내지 않는다 (지금 결과처럼 보이지 않게 파란 꼬리표와 옅은 점선 상자로 구분)
export function NextStep({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div
      style={{
        display: 'flex',
        gap: 8,
        alignItems: 'flex-start',
        flexWrap: 'wrap',
        padding: '10px 14px',
        border: '1px dashed var(--line-neutral-secondary, #c9ccd1)',
        borderRadius: 8,
      }}
    >
      <Tag color="blue" bordered={false} style={{ marginInlineEnd: 0 }}>
        다음 단계
      </Tag>
      <div style={{ flex: '1 1 300px', display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span className="body2" style={{ fontWeight: 600 }}>
          {title}
        </span>
        <span className="label1 t2">{children}</span>
      </div>
    </div>
  )
}
