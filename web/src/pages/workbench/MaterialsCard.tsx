import { Button } from 'antd'
import { useState } from 'react'
import { useLocation } from 'react-router'
import { MaterialRows } from '../../components/MaterialRows'
import type { CaseMaterials } from '../../types/generated/CaseMaterials'
import type { OAResult } from '../../types/generated/OAResult'

// 사건 자료: "사건 자료 N건" 제목 줄. 찾아온 자료(documents) · 못 가져온 자료(missing) · 보류한 작업(held_tasks)을 줄로.
// 빠진 자료가 있으면 펼쳐서 보이고, 없으면 접고 "자세히". 직접 누른 것이 그 뒤를 이긴다
export function MaterialsCard({ m, r, caseId }: { m: CaseMaterials; r: OAResult; caseId: string }) {
  // 펼침: 누른 것은 그때의 주소 key와 묶는다. 새 주소(#materials, 직접 할 일 "자료 보기")로 오면 펼쳐서 보인다 (effect 없이 계산)
  const location = useLocation()
  const [pressed, setPressed] = useState<{ key: string; open: boolean } | null>(null)
  const open = pressed?.key === location.key ? pressed.open : location.hash === '#materials' || m.missing.length > 0
  const count = m.documents.length + m.missing.length

  return (
    <div id="materials" style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <h2 className="heading2" style={{ flex: '1 1 auto' }}>
          사건 자료 {count}건
        </h2>
        {m.missing.length > 0 && <span className="label1 t3">못 가져온 자료 {m.missing.length}건</span>}
        <Button type="link" onClick={() => setPressed({ key: location.key, open: !open })}>
          {open ? '접기' : '자세히'}
        </Button>
      </div>
      {open && (
        <>
          <MaterialRows m={m} r={r} caseId={caseId} />
          {/* 보류한 작업: 기다리는 자료가 오면 이어서 한다. 나머지 작업은 진행 */}
          {m.held_tasks.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '12px 0' }}>
              <span className="label2 t3">원문 확인 필요한 작업 {m.held_tasks.length}건 · 나머지 작업은 진행해요</span>
              {m.held_tasks.map((h) => (
                <span key={`${h.task}-${h.waiting_for}`} className="body2 t2">
                  {h.task} — 기다리는 자료: {h.waiting_for}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
