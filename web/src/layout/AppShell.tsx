import { Button, Popconfirm, Spin, Tag } from 'antd'
import { Link, Outlet, useLocation, useNavigation } from 'react-router'
import { API_MODE, resetMockStorage } from '../api'

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
        className="app-header"
        style={{
          display: 'flex',
          alignItems: 'center',
          minHeight: 56,
          padding: '8px 32px',
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
        {/* 고른 것·고친 것·실행 흉내를 지우고 처음 예시로 (mock에서만) */}
        {API_MODE === 'mock' && (
          <Popconfirm
            title="mock 처음으로"
            description="고른 방향·고친 초안·실행 진행을 지우고 새로고침해요."
            okText="지우기"
            cancelText="취소"
            onConfirm={resetMockStorage}
          >
            <Button type="text" size="small" className="label2 t3">
              mock 처음으로
            </Button>
          </Popconfirm>
        )}
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
