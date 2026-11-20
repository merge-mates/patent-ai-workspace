import { Button, Result } from 'antd'
import { Link, isRouteErrorResponse, useRouteError } from 'react-router'
import { ApiError } from '../api/errors'

// 데이터를 못 받으면 조용히 빈 화면을 두지 않고 이유를 보인다
export function RouteError() {
  const error = useRouteError()
  let title = '화면을 열지 못했습니다'
  let detail = '알 수 없는 오류'
  if (error instanceof ApiError) {
    detail = `${error.message} (${error.code})`
  } else if (isRouteErrorResponse(error)) {
    title = `${error.status} ${error.statusText}`
    detail = String(error.data ?? '')
  } else if (error instanceof Error) {
    detail = error.message
  }
  return (
    <Result
      status="warning"
      title={title}
      subTitle={detail}
      extra={
        <Link to="/cases">
          <Button type="primary">사건 목록으로</Button>
        </Link>
      }
    />
  )
}
