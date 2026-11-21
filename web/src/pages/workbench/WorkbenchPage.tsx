import { Button, Result, Space, Typography } from 'antd'
import { useState } from 'react'
import { useLocation, useRouteLoaderData } from 'react-router'
import { ReviewPanel } from '../../components/ReviewPanel'
import { StatusTag } from '../../components/StatusTag'
import { TodoRows } from '../../components/TodoList'
import { runStateLabel } from '../../labels'
import type { OALoaderData } from '../../loaders'
import { directTodos } from '../../todos'
import { HintsCard } from './HintsCard'
import { MaterialsCard } from './MaterialsCard'
import { RejectionsCard } from './RejectionsCard'

// 사건 작업 1 정리: 직접 할 일 → 거절이유 정리 → 심사관 힌트 → 사건 자료 → 검토할 사항.
// 통지 정보는 사건 틀 머리의 "사건 정보"로, 원문은 오른쪽 판으로 옮겼다
export function WorkbenchPage() {
  const data = useRouteLoaderData('oa') as OALoaderData
  const { oa, oaResult, materials, reviewItems } = data
  const location = useLocation()
  // 검토할 사항 펼침: "전체 보기"로 #review-items 주소로 왔으면 펼쳐 있고, 직접 누른 것이 그 뒤면 그게 이긴다.
  // 눌렀을 때의 주소 key를 같이 적어 두어, 같은 주소로 다시 와도(새 key) 주소 쪽을 따른다 (effect 없이 계산)
  const [pressed, setPressed] = useState<{ key: string; open: boolean } | null>(null)
  const showReview = pressed?.key === location.key ? pressed.open : location.hash === '#review-items'

  if (oaResult === null) {
    // 결과가 없으면 빈 표 대신 실행 상태를 보인다. 실패·취소를 "정리 중"으로 보이지 않게 나눈다
    const run = oa.latest_run
    const step = run.current_step ? ` · ${run.current_step}` : ''
    if (run.state === 'failed') {
      return <Result status="error" title="정리하지 못했습니다" subTitle={`${runStateLabel[run.state]}${step}`} />
    }
    if (run.state === 'cancelled') {
      return <Result status="warning" title="정리를 취소했습니다" subTitle={`${runStateLabel[run.state]}${step}`} />
    }
    return <Result status="info" title="아직 정리하는 중입니다" subTitle={`${runStateLabel[run.state]}${step}`} />
  }
  const r = oaResult.result
  const todos = directTodos(data)
  const reviewCount = reviewItems?.length ?? materials?.review_items_count ?? null

  return (
    <>
      {/* 사람이 해야 할 일. 목록을 모르면 개수도 모름 (0으로 그리지 않는다) */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <h2 className="heading2" style={{ marginBottom: 8 }}>
          직접 할 일 {todos === null ? '(모름)' : todos.length}
        </h2>
        {todos === null ? (
          <span className="body2 t3">
            검토할 사항 목록을 받지 못해 직접 할 일을 알 수 없어요. 제출기일은 통지서에서 직접 확인해 주세요.
          </span>
        ) : (
          <TodoRows todos={todos} variant="page" />
        )}
      </div>

      <RejectionsCard r={r} legal={data.legal} />
      <HintsCard h={r.examiner_hints} />
      {materials ? (
        <MaterialsCard m={materials} r={r} />
      ) : (
        <div id="materials" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <h2 className="heading2">사건 자료 (모름)</h2>
          <Space>
            <StatusTag status="unverified" />
            <Typography.Text type="secondary">사건 자료 목록을 받지 못했습니다</Typography.Text>
          </Space>
        </div>
      )}

      {/* 검토할 사항 (확인되지 않음·충돌 등 전부): 직접 할 일과 다른 숫자라 아래쪽에 따로 */}
      <div id="review-items" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <h2 className="heading2" style={{ flex: '1 1 auto' }}>
            {reviewCount === null ? '검토할 사항 (모름)' : `검토할 사항 ${reviewCount}건`}
          </h2>
          <Button type="link" onClick={() => setPressed({ key: location.key, open: !showReview })}>
            {showReview ? '접기' : '자세히'}
          </Button>
        </div>
        {showReview && <ReviewPanel items={reviewItems} count={reviewCount} />}
      </div>
    </>
  )
}
