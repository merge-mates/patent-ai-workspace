import { Card, Result, Space, Typography } from 'antd'
import { useState } from 'react'
import { useRouteLoaderData } from 'react-router'
import { SourceContext } from '../../components/sourceContext'
import { StatusTag } from '../../components/StatusTag'
import { runStateLabel } from '../../labels'
import type { OALoaderData } from '../../loaders'
import { HintsCard } from './HintsCard'
import { MaterialsCard } from './MaterialsCard'
import { NoticeCard } from './NoticeCard'
import { RejectionsCard } from './RejectionsCard'
import { SourceDrawer } from './SourceDrawer'

// 사건 작업대 (1 자료 · 2 거절이유 정리): 통지 정보 → 사건 자료 → 거절이유 정리 → 심사관 힌트
export function WorkbenchPage() {
  const { oa, oaResult, materials, document } = useRouteLoaderData('oa') as OALoaderData
  // 원문 보기 Drawer: 어느 쪽, 어느 글자를 강조할지
  const [source, setSource] = useState<{ page: number; text: string | null } | null>(null)

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

  return (
    <SourceContext value={(page, text) => setSource({ page, text })}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <NoticeCard r={r} />
        {materials ? (
          <MaterialsCard m={materials} r={r} />
        ) : (
          <Card size="small" title="사건 자료" id="materials">
            <Space>
              <StatusTag status="unverified" />
              <Typography.Text type="secondary">사건 자료 목록을 받지 못했습니다</Typography.Text>
            </Space>
          </Card>
        )}
        <RejectionsCard r={r} />
        <HintsCard h={r.examiner_hints} />
      </Space>
      <SourceDrawer
        open={source !== null}
        page={source?.page ?? null}
        highlight={source?.text ?? null}
        document={document}
        onClose={() => setSource(null)}
      />
    </SourceContext>
  )
}
