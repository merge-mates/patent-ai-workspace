import { Col, Menu, Row, Typography } from 'antd'
import { Outlet, useLocation, useNavigate, useRouteLoaderData } from 'react-router'
import { ReviewPanel } from '../components/ReviewPanel'
import type { OALoaderData } from '../loaders'

// 사건 안의 단계: 일하는 순서대로. 아직 안 만든 단계는 잠가 둔다
type Step = { key: string; label: string; path: string; anchor?: string; disabled?: boolean }
const STEPS: Step[] = [
  { key: 'materials', label: '1 자료', path: '', anchor: 'materials' },
  { key: 'rejections', label: '2 거절이유 정리', path: '', anchor: 'rejections' },
  { key: 'compare', label: '3 대비와 근거', path: '/compare' },
  { key: 'directions', label: '4 대응 방향', path: '/directions' },
  { key: 'drafts', label: '5 의견서·보정 초안', path: '/drafts', disabled: true },
]

// 사건 틀: 왼쪽 단계 메뉴 · 가운데 본문 · 오른쪽 "검토할 사항" 판
// 좁은 화면에서는 본문이 먼저, 메뉴·판은 아래로 내려간다 (order)
export function CaseShell() {
  const data = useRouteLoaderData('oa') as OALoaderData
  const navigate = useNavigate()
  const location = useLocation()
  const base = `/oas/${data.oa.oa_id}`
  const sub = location.pathname.slice(base.length)
  const current = STEPS.find((s) => s.path !== '' && s.path === sub)?.key ?? 'rejections'

  // 같은 화면 안 단계(1·2)는 그 칸으로 내려가고, 다른 단계는 그 경로로 간다
  const go = (key: string) => {
    const step = STEPS.find((s) => s.key === key)!
    if (step.anchor) {
      if (sub !== '') navigate(base)
      document.getElementById(step.anchor)?.scrollIntoView({ behavior: 'smooth' })
      return
    }
    navigate(base + step.path)
  }

  return (
    <Row gutter={[16, 16]}>
      <Col xs={{ span: 24, order: 2 }} lg={{ span: 4, order: 1 }}>
        <Typography.Text strong style={{ display: 'block', marginBottom: 8 }}>
          {data.oa.case_name}
        </Typography.Text>
        <Menu
          mode="inline"
          selectedKeys={[current]}
          onClick={({ key }) => go(key)}
          style={{ borderInlineEnd: 'none', background: 'transparent' }}
          items={STEPS.map((s) => ({ key: s.key, label: s.label, disabled: s.disabled }))}
        />
      </Col>
      <Col xs={{ span: 24, order: 1 }} lg={{ span: 14, order: 2 }}>
        <Outlet />
      </Col>
      <Col xs={{ span: 24, order: 3 }} lg={{ span: 6, order: 3 }}>
        <div style={{ position: 'sticky', top: 16 }}>
          <ReviewPanel items={data.reviewItems} count={data.materials?.review_items_count ?? null} />
        </div>
      </Col>
    </Row>
  )
}
