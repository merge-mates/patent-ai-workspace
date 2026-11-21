import type { ReactNode } from 'react'
import { Result } from 'antd'
import { useLoaderData } from 'react-router'

// 단계 주소를 직접 열었는데 실행 중이라 결과가 아직 없을 때(loader가 null): 오류 화면 대신 안내를 보인다
export function ResultGate({ children }: { children: ReactNode }) {
  const data = useLoaderData() as unknown
  if (data === null) {
    return <Result status="info" title="아직 결과가 없어요" subTitle="실행이 끝나면 보여요. 위 단계 막대에서 진행을 볼 수 있어요." />
  }
  return children
}
