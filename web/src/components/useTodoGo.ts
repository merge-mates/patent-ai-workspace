import { useContext } from 'react'
import { useNavigate, useRouteLoaderData } from 'react-router'
import type { OALoaderData } from '../loaders'
import type { TodoGo } from '../todos'
import { SourceContext } from './sourceContext'

// "가기" 버튼이 하는 일. 어느 단계에서든 같게 동작한다:
// 원문 판을 그 쪽으로 / 정리 단계의 그 자리(id)로 / 다른 단계로
export function useTodoGo(): (go: TodoGo) => void {
  const openSource = useContext(SourceContext)
  const navigate = useNavigate()
  const { oa } = useRouteLoaderData('oa') as OALoaderData
  const base = `/oas/${oa.oa_id}`
  return (go) => {
    if (go.kind === 'source') openSource(go.page, go.text)
    // 자리로 가기: 주소 끝 #id → 사건 틀의 ScrollRestoration이 그 자리로 내린다
    else if (go.kind === 'anchor') navigate({ pathname: base, hash: `#${go.id}` })
    else navigate(base + go.path)
  }
}
