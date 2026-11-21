import { ApiError } from './api/errors'

// 올리기(POST /cases, POST /cases/{id}/oas)가 409 document_already_exists로 막혔을 때, 이미 있는 사건으로 가는 주소.
// 서버가 오류 본문에 case_id·oa_id를 같이 준다 (ApiError.extra). oa_id가 있으면 그 통지서로, 없으면 사건으로.
// 올리는 곳이 여럿이어도 이 함수 하나만 쓴다. 해당 오류가 아니거나 둘 다 없으면 null
export function existingCaseLink(e: unknown): string | null {
  if (!(e instanceof ApiError) || e.code !== 'document_already_exists') return null
  const { oa_id, case_id } = e.extra
  if (typeof oa_id === 'string' && oa_id !== '') return `/oas/${encodeURIComponent(oa_id)}`
  if (typeof case_id === 'string' && case_id !== '') return `/cases/${encodeURIComponent(case_id)}`
  return null
}
