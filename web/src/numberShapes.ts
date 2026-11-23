// 사람이 넣는 번호의 꼴 검사 (화면 폼과 mock이 같이 쓴다). 서버가 다시 맞추니 가볍게만 본다.
// 출원번호: 하이픈을 빼고 숫자 13자리 (예: 10-0000-0000000)
export const isApplicationNumberShape = (text: string): boolean => /^\d{13}$/.test(text.replace(/-/g, '').trim())

// 발송번호: 서버 normalize_dispatch_number 꼴 9-5-YYYY-NNNNNNNNN (하이픈은 있어도 없어도 됨)
export const isDispatchNumberShape = (text: string): boolean => /^9-?5-?\d{4}-?\d{9}$/.test(text.trim())

// 화면에 보일 때만 하이픈을 넣는다 (사람이 넣은 번호는 하이픈 없이 저장된다). 저장 값은 바꾸지 않는다.
// 종류마다 자기 꼴의 숫자일 때만 넣고, 그 밖의 글자(자리수가 틀린 후보 등)는 그대로 돌려준다.
// 통지서 글자가 하이픈 없는 숫자였어도 보일 때는 하이픈이 붙는다 (원문 글자는 원문 보기에서 본다)
// 출원번호: 숫자 13자리 → 10-0000-0000000 (2-4-7)
export const showApplicationNumber = (text: string): string =>
  /^\d{13}$/.test(text) ? `${text.slice(0, 2)}-${text.slice(2, 6)}-${text.slice(6)}` : text
// 발송번호: 95로 시작하는 숫자 15자리 → 9-5-YYYY-NNNNNNNNN (1-1-4-9)
export const showDispatchNumber = (text: string): string =>
  /^95\d{13}$/.test(text) ? `9-5-${text.slice(2, 6)}-${text.slice(6)}` : text
