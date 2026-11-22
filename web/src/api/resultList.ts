// F3·F4 결과 목록 + 빈 이유 (#191 결과 응답 {oa_id, run_id, result, empty_reason}에서 화면이 쓰는 두 칸).
// 실행은 끝났는데 목록이 비면 서버가 empty_reason에 이유를 준다:
//   "넘김: <이유>" / "보류: <기다리는 것>" / "확인되지 않음: <이유>" / "해당 거절이유 없음" 등 (docs/api/README.md 19줄)
// 목록이 있으면 emptyReason은 null이다
export interface ResultList<T> {
  items: T[]
  emptyReason: string | null
}
