import { ApiError } from './api/errors'

// 방향 고르기·직접 쓰기 저장(PUT /directions/{unit_id}/selection)이 실패했을 때 사람에게 보일 글. 문구는 이 한 곳에만 둔다.
// 알려진 코드(409·422)는 뜻을 풀어 쓰고, 그 밖은 지금처럼 메시지 + 코드
export function selectionErrorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code === 'run_in_progress') return '다른 실행이 끝난 뒤 다시 골라 주세요'
    if (e.code === 'candidate_not_found') return '이 청구항들의 후보가 아니에요. 화면을 새로 불러온 뒤 다시 골라 주세요'
    if (e.code === 'invalid_selection') return '후보 하나나 직접 쓴 글 하나만 보낼 수 있어요 (빈 글은 안 돼요)'
    return `${e.message} (${e.code})`
  }
  return e instanceof Error ? e.message : String(e)
}
