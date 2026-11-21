import { UploadOutlined } from '@ant-design/icons'
import { Button, Tooltip } from 'antd'
import { useState } from 'react'
import { useLocation } from 'react-router'
import { HumanCheckTag } from '../../components/Marks'
import { StatusTag } from '../../components/StatusTag'
import { lookupResultLabel, materialKindLabel, sourceLabel } from '../../labels'
import type { CaseMaterials } from '../../types/generated/CaseMaterials'
import type { OAResult } from '../../types/generated/OAResult'

const lineStyle = {
  display: 'flex',
  gap: 12,
  alignItems: 'center',
  flexWrap: 'wrap',
  padding: '12px 0',
  borderBottom: '1px solid var(--line-neutral-tertiary)',
} as const

// 사건 자료: "사건 자료 N건" 제목 줄. 찾아온 자료(documents) · 못 가져온 자료(missing) · 보류한 작업(held_tasks)을 줄로.
// 빠진 자료가 있으면 펼쳐서 보이고, 없으면 접고 "자세히". 직접 누른 것이 그 뒤를 이긴다
export function MaterialsCard({ m, r }: { m: CaseMaterials; r: OAResult }) {
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
          {/* 찾아온 자료. 상태는 "받음"이 아니라 묶기 상태 (다른 출원번호 문서가 묻히지 않게). 확인됨은 꼬리표 없음 */}
          {m.documents.map((d) => (
            <div key={d.document_id} style={lineStyle}>
              <span className="body1" style={{ fontWeight: 600, flex: '0 1 220px' }}>
                {materialKindLabel[d.kind] ?? d.kind}
              </span>
              <span className="body2 t2" style={{ flex: '1 1 240px' }}>
                {/* 통지서는 어느 판인지 발송번호로 (날짜만으로 합치지 않음) */}
                {d.kind === 'oa' ? `발송번호 ${r.dispatch_number.raw_text ?? r.dispatch_number.value ?? '모름'} · ` : ''}
                {sourceLabel[d.source] ?? d.source}
              </span>
              {d.status.value !== 'confirmed' && <StatusTag status={d.status} />}
            </div>
          ))}
          {/* 못 가져온 자료. 공개공보·등록공보는 다른 판이라 판을 짐작하지 않는다 */}
          {m.missing.map((x, i) => (
            <div key={`missing-${i}`} style={lineStyle}>
              <span className="body1" style={{ fontWeight: 600, flex: '0 1 220px' }}>
                {x.what}
              </span>
              <span className="body2 t2" style={{ flex: '1 1 240px' }}>
                {[lookupResultLabel[x.lookup_result], '판 모름', '자동 조회'].join(' · ')}
              </span>
              {x.lookup_result === 'unsupported_country' ? (
                <HumanCheckTag>직접 확인</HumanCheckTag>
              ) : (
                <StatusTag status={{ value: 'unverified', reason: x.lookup_result, checked: null, searched_scope: null }} />
              )}
              {x.ask_upload && (
                // 올리기 API(POST /cases/{id}/documents)가 web/src/api에 아직 없어 누를 수 없다
                <Tooltip title="서버가 오면 올릴 수 있어요">
                  <span>
                    <Button size="small" icon={<UploadOutlined />} disabled>
                      올려 주세요
                    </Button>
                  </span>
                </Tooltip>
              )}
            </div>
          ))}
          {m.documents.length + m.missing.length === 0 && (
            <span className="body2 t3" style={{ padding: '12px 0' }}>
              사건 자료가 아직 없어요
            </span>
          )}
          {/* 보류한 작업: 기다리는 자료가 오면 이어서 한다. 나머지 작업은 진행 */}
          {m.held_tasks.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '12px 0' }}>
              <span className="label2 t3">보류한 작업 {m.held_tasks.length}건 · 나머지 작업은 진행해요</span>
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
