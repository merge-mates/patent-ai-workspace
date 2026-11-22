// 사람이 넣는 번호의 꼴 검사 (화면 폼과 mock이 같이 쓴다). 서버가 다시 맞추니 가볍게만 본다.
// 출원번호: 하이픈을 빼고 숫자 13자리 (예: 10-0000-0000000)
export const isApplicationNumberShape = (text: string): boolean => /^\d{13}$/.test(text.replace(/-/g, '').trim())

// 발송번호: 서버 normalize_dispatch_number 꼴 9-5-YYYY-NNNNNNNNN (하이픈은 있어도 없어도 됨)
export const isDispatchNumberShape = (text: string): boolean => /^9-?5-?\d{4}-?\d{9}$/.test(text.trim())
