// 서버 오류 본문은 한 형식 {code, message}에 오류별 칸이 더 붙을 수 있다 (docs/api/README.md 2절)
export class ApiError extends Error {
  readonly code: string
  readonly httpStatus: number
  // {code, message} 밖의 칸 (예: 409 document_already_exists의 case_id·oa_id)
  readonly extra: Record<string, unknown>

  constructor(code: string, message: string, httpStatus: number, extra: Record<string, unknown> = {}) {
    super(message)
    this.code = code
    this.httpStatus = httpStatus
    this.extra = extra
  }
}

// 결과가 아직 없음 (실행 전·실행 중): 404 {code: "result_not_ready"}
export const isNotReady = (e: unknown) => e instanceof ApiError && e.code === 'result_not_ready'
