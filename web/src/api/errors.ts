// 서버 오류 본문은 한 형식 {code, message} (docs/api/README.md 2절)
export class ApiError extends Error {
  readonly code: string
  readonly httpStatus: number

  constructor(code: string, message: string, httpStatus: number) {
    super(message)
    this.code = code
    this.httpStatus = httpStatus
  }
}

// 결과가 아직 없음 (실행 전·실행 중): 404 {code: "result_not_ready"}
export const isNotReady = (e: unknown) => e instanceof ApiError && e.code === 'result_not_ready'
