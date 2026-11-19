import { FileTextOutlined } from '@ant-design/icons'
import { Typography } from 'antd'
import { useContext } from 'react'
import { SourceContext } from './sourceContext'

// 원문 쪽 링크: 누르면 그 쪽 글자를 열고 근거 글자를 강조한다
export function SourceLink({ page, rawText }: { page: number | null; rawText: string | null }) {
  const open = useContext(SourceContext)
  if (page === null) return null
  return (
    <Typography.Link onClick={() => open(page, rawText)} style={{ whiteSpace: 'nowrap', fontSize: 12 }}>
      <FileTextOutlined /> 원문 {page}쪽
    </Typography.Link>
  )
}
