import { createContext } from 'react'

// "원문 n쪽" 링크·"가기" 버튼을 누르면 사건 틀(CaseShell)이 오른쪽 원문 판을 그 쪽으로 연다.
// 링크는 어디에 있든 이 함수만 부른다. 쪽을 모르면(null) 판만 펴고 보던 쪽은 그대로 둔다
export type OpenSource = (page: number | null, rawText: string | null) => void

export const SourceContext = createContext<OpenSource>(() => {})
