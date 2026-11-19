import { UserOutlined } from '@ant-design/icons'
import { Layout, Menu, Space, Spin, Tag, Typography } from 'antd'
import { Link, Outlet, useLocation, useNavigation } from 'react-router'
import { API_MODE } from '../api'

// 공통 틀: 위 머리 막대(서비스 이름, 메뉴 "사건"·"법률 질문", 오른쪽 "기본 사용자")
export function AppShell() {
  const location = useLocation()
  const navigation = useNavigation()
  const selected = location.pathname.startsWith('/legal') ? 'legal' : 'cases'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          background: '#fff',
          borderBottom: '1px solid #f0f0f0',
          paddingInline: 16,
        }}
      >
        <Link to="/cases">
          <Typography.Title level={5} style={{ margin: 0, whiteSpace: 'nowrap' }}>
            거절은거절해
          </Typography.Title>
        </Link>
        <Menu
          mode="horizontal"
          selectedKeys={[selected]}
          style={{ flex: 1, minWidth: 0, borderBottom: 'none' }}
          items={[
            { key: 'cases', label: <Link to="/cases">사건</Link> },
            { key: 'legal', label: <Link to="/legal">법률 질문</Link> },
          ]}
        />
        <Space size={8}>
          {navigation.state === 'loading' && <Spin size="small" />}
          {API_MODE === 'mock' && <Tag>mock 데이터</Tag>}
          <Space size={4}>
            <UserOutlined />
            <Typography.Text>기본 사용자</Typography.Text>
          </Space>
        </Space>
      </Layout.Header>
      <Layout.Content style={{ padding: 16 }}>
        <Outlet />
      </Layout.Content>
    </Layout>
  )
}
