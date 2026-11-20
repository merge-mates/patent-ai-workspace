import { createContext } from 'react'

// "원문 n쪽" 링크를 누르면 작업대가 Drawer를 연다. 링크는 어디에 있든 이 함수만 부른다
export type OpenSource = (page: number, rawText: string | null) => void

export const SourceContext = createContext<OpenSource>(() => {})
