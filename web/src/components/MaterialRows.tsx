import { Button, Tooltip } from 'antd'
import { HumanCheckTag } from './Marks'
import { StatusTag } from './StatusTag'
import { UploadMaterialButton } from './UploadMaterialButton'
import { materialKindLabel, sourceLabel } from '../labels'
import { showDispatchNumber } from '../numberShapes'
import type { CaseMaterials } from '../types/generated/CaseMaterials'
import type { OAResult } from '../types/generated/OAResult'

const lineStyle = {
  display: 'flex',
  gap: 12,
  alignItems: 'center',
  flexWrap: 'wrap',
  padding: '12px 0',
  borderBottom: '1px solid var(--line-neutral-tertiary)',
} as const

// 사건 자료 줄: 찾아온 자료(documents) + 못 가져온 자료(missing). 사건 정리 단계와 사건 올리기 화면이 같이 쓴다.
// showRetry면 "조회 실패" 줄에 "다시 조회" 버튼도 둔다 (다시 조회 API는 아직 없어 누를 수 없다)
export function MaterialRows({
  m,
  r,
  caseId,
  showRetry = false,
  specDocumentId = null,
}: {
  m: CaseMaterials
  r: OAResult | null
  caseId: string
  showRetry?: boolean
  // 사건 정보에서 찾은 출원 명세서 문서 ID. 사건 자료 목록에 없으면 줄을 하나 더해 보인다 (원문 판의 명세서 탭과 맞춘다)
  specDocumentId?: string | null
}) {
  const extraSpec = specDocumentId !== null && !m.documents.some((d) => d.document_id === specDocumentId)
  return (
    <>
      {extraSpec && (
        <div style={lineStyle}>
          <div style={{ flex: '1 1 260px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="body2" style={{ fontWeight: 600 }}>
              명세서 (출원서)
            </span>
            <span className="label1 t3">출원 때 판 · 오른쪽 원문 판의 명세서 탭에서 볼 수 있어요</span>
          </div>
        </div>
      )}
      {/* 찾아온 자료. 상태는 "받음"이 아니라 묶기 상태 (다른 출원번호 문서가 묻히지 않게). 확인됨은 꼬리표 없음 */}
      {m.documents.map((d) => (
        <div key={d.document_id} style={lineStyle}>
          <div style={{ flex: '1 1 260px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="body2" style={{ fontWeight: 600 }}>
              {materialKindLabel[d.kind] ?? d.kind}
              {/* 인용문헌은 어느 문헌인지 번호까지 */}
              {d.citation_key ? ` ${d.citation_key}` : ''}
            </span>
            <span className="label1 t3">
              {/* 통지서는 어느 판인지 발송번호로 (날짜만으로 합치지 않음) */}
              {d.kind === 'oa' && r ? `발송번호 ${showDispatchNumber(r.dispatch_number.raw_text ?? r.dispatch_number.value ?? '모름')} · ` : ''}
              {sourceLabel[d.source] ?? d.source}
            </span>
          </div>
          {d.status.value !== 'confirmed' && <StatusTag status={d.status} />}
        </div>
      ))}
      {/* 못 가져온 자료. 공개공보·등록공보는 다른 판이라 판을 짐작하지 않는다 */}
      {m.missing.map((x, i) => (
        <div key={`missing-${i}`} style={lineStyle}>
          <div style={{ flex: '1 1 260px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="body2" style={{ fontWeight: 600 }}>
              {x.what}
            </span>
            {/* 이유는 오른쪽 상태 꼬리표에 있어 같은 말을 두 번 쓰지 않는다 ("판 모름 · 자동 조회"는 개발용이라 뺌) */}
          </div>
          {x.lookup_result === 'unsupported_country' ? (
            <HumanCheckTag>직접 확인</HumanCheckTag>
          ) : (
            <StatusTag status={{ value: 'unverified', reason: x.lookup_result, checked: null, searched_scope: null }} />
          )}
          {showRetry && x.lookup_result === 'lookup_failed' && (
            <Tooltip title="다시 조회는 서버가 오면 할 수 있어요">
              <span>
                <Button size="small" disabled>
                  다시 조회
                </Button>
              </span>
            </Tooltip>
          )}
          {x.ask_upload && <UploadMaterialButton caseId={caseId} what={x.what} />}
        </div>
      ))}
      {m.documents.length + m.missing.length === 0 && (
        <span className="body2 t3" style={{ padding: '12px 0' }}>
          사건 자료가 아직 없어요
        </span>
      )}
    </>
  )
}
