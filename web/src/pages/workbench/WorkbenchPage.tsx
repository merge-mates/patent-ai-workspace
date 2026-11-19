import { Result, Space } from 'antd'
import { useState } from 'react'
import { useRouteLoaderData } from 'react-router'
import { SourceContext } from '../../components/sourceContext'
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
    // 실행이 안 끝났으면 빈 표 대신 지금 하는 작업을 보인다
    return (
      <Result
        status="info"
        title="아직 정리하는 중입니다"
        subTitle={`${runStateLabel[oa.latest_run.state]}${oa.latest_run.current_step ? ` · ${oa.latest_run.current_step}` : ''}`}
      />
    )
  }
  const r = oaResult.result

  return (
    <SourceContext value={(page, text) => setSource({ page, text })}>
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <NoticeCard r={r} />
        <MaterialsCard m={materials} r={r} />
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
