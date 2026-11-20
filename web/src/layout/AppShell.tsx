import { Button, Spin, Tag } from 'antd'
import { Link, Outlet, useLocation, useNavigation } from 'react-router'
import { API_MODE } from '../api'

// 공통 틀 (디자인 B 고친 판): 높이 56 머리 막대 = 서비스 이름 · 메뉴 두 개(글자 링크) · 통지서 올리기 · 아바타
export function AppShell() {
  const location = useLocation()
  const navigation = useNavigation()
  const onLegal = location.pathname.startsWith('/legal')

  // 지금 메뉴는 진하게, 나머지는 옅은(tertiary) 색
  const navStyle = (on: boolean) => ({
    fontWeight: 600,
    color: on ? 'var(--fg-neutral-primary)' : 'var(--fg-neutral-tertiary)',
  })

  return (
    <div style={{ minHeight: '100vh', background: '#fff' }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 32,
          height: 56,
          padding: '0 32px',
          borderBottom: '1px solid var(--line-neutral-tertiary)',
          flexWrap: 'wrap',
        }}
      >
        <Link to="/cases" style={{ fontSize: 17, fontWeight: 700, color: 'var(--fg-neutral-primary)' }}>
          거절은거절해
        </Link>
        <nav style={{ display: 'flex', gap: 24, flex: '1 1 auto' }}>
          <Link to="/cases" className="body2" style={navStyle(!onLegal)}>
            사건
          </Link>
          <Link to="/legal" className="body2" style={navStyle(onLegal)}>
            법률 질문
          </Link>
        </nav>
        {navigation.state === 'loading' && <Spin size="small" />}
        {/* 데이터가 가짜임을 숨기지 않는다 */}
        {API_MODE === 'mock' && <Tag style={{ marginInlineEnd: 0 }}>mock 데이터</Tag>}
        <Link to="/cases/new">
          <Button type="primary">통지서 올리기</Button>
        </Link>
        <span className="avatar" aria-label="기본 사용자">
          기본
        </span>
      </header>
      {/* 본문 여백은 각 화면이 갖는다 */}
      <Outlet />
    </div>
  )
}
