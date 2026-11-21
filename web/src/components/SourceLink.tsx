import { FileTextOutlined } from '@ant-design/icons'
import { Typography } from 'antd'
import { useContext } from 'react'
import { SourceContext } from './sourceContext'

// 원문 쪽 링크: 누르면 그 쪽 글자를 열고 근거 글자를 강조한다
// candidate: 확인된 값이 아니면 "원문"이 아니라 "후보 위치"로 적는다 (F5: 원문 링크는 확인된 값만)
export function SourceLink({
  page,
  rawText,
  candidate = false,
}: {
  page: number | null
  rawText: string | null
  candidate?: boolean
}) {
  const { openPage: open } = useContext(SourceContext)
  if (page === null) return null
  return (
    <Typography.Link onClick={() => open(page, rawText)} style={{ whiteSpace: 'nowrap', fontSize: 12 }}>
      <FileTextOutlined /> {candidate ? `후보 위치 ${page}쪽` : `원문 ${page}쪽`}
    </Typography.Link>
  )
}
