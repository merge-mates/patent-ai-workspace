import { Divider, Space, Typography } from 'antd'
import { StatusTag } from './StatusTag'

// 상태 네 가지 보기: 처음 보는 사람도 꼬리표 뜻을 알게
export function StatusLegend() {
  return (
    <>
      <Divider style={{ margin: '8px 0' }} />
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
        상태 보기
      </Typography.Text>
      <Space size={[0, 4]} wrap style={{ marginTop: 4 }}>
        {/* 확인됨은 꼬리표 없이 체크 + 초록 글자 */}
        <span style={{ marginInlineEnd: 8 }}>
          <StatusTag status="confirmed" />
        </span>
        <StatusTag status="unverified" />
        <StatusTag status="not_found_in_scope" />
        <StatusTag status="conflict" />
      </Space>
    </>
  )
}
