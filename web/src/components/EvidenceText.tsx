import { Typography } from 'antd'
import type { Evidence1 as Evidence } from '../types/generated/Drafts'

// 근거 한 줄: 원문 글자(있으면) + 위치. 위치는 location 글자, 없으면 쪽 번호, 그것도 없으면 문서 번호
export function EvidenceText({ e }: { e: Evidence }) {
  const where = e.location ?? (e.page !== null ? `${e.page}쪽` : e.document_id)
  return (
    <>
      {e.raw_text && <>“{e.raw_text}” </>}
      <Typography.Text type="secondary">({where})</Typography.Text>
    </>
  )
}
