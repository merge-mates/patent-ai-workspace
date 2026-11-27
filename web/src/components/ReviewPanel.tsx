import { Button, Space, Tag, Typography } from 'antd'
import { articleLabel, heldTaskLabel, lookupResultLabel, unverifiedReasonLabel } from '../labels'
import { reviewTargetGo } from '../todos'
import type { CaseMaterials } from '../types/generated/CaseMaterials'
import type { OAResult } from '../types/generated/OAResult'
import type { ReviewItem } from '../types/generated/ReviewItem'
import { HumanCheckTag } from './Marks'
import { StatusLegend } from './StatusLegend'
import { StatusTag } from './StatusTag'
import { UploadMaterialButton } from './UploadMaterialButton'
import { useTodoGo } from './useTodoGo'
import { mergeDetails, reviewDetail } from './reviewDetail'
import { SourceContext } from './sourceContext'
import { useContext } from 'react'

interface Props {
  // 목록을 모르면 null (⑥ review_items가 None): 개수가 있어도 "모름"으로 본다 ("0건"으로 보이지 않게)
  items: ReviewItem[] | null
  // 줄을 누르면 갈 자리(target)와 빠진 자료 줄의 올리기·보류를 찾는 데 쓴다
  r: OAResult | null
  materials: CaseMaterials | null
  caseId: string
}

// 검토할 사항 종류마다 같은 꼬리표 (상태 네 가지 + 사람이 할 일)
function KindTag({ item }: { item: ReviewItem }) {
  switch (item.kind) {
    case 'unverified':
      return <StatusTag status="unverified" />
    case 'conflict':
      return <StatusTag status="conflict" />
    case 'needs_human_judgment':
      return <HumanCheckTag>직접 판단 필요</HumanCheckTag>
    case 'needs_human_review':
      return <HumanCheckTag>직접 검토 필요</HumanCheckTag>
    case 'needs_recheck':
      return <Tag color="orange">다시 확인 필요</Tag>
    case 'missing_material':
      return <Tag color="volcano">빠진 자료</Tag>
  }
}

// reason이 코드(확인 안 된 이유·빠진 자료 조회 결과)면 한국어로, 글이면 그대로
const reasonCodes: Record<string, string> = { ...unverifiedReasonLabel, ...lookupResultLabel }
function reasonText(reason: string): string {
  // 글 끝의 조문 코드("… 29-1")도 "특허법 제29조제1항"으로
  return reasonCodes[reason] ?? reason.replace(/ (\d+-\d+(?:-\d+)?)$/, (_, code: string) => ` (특허법 ${articleLabel(code)})`)
}

// 정리 단계 아래쪽 "검토할 사항 N건"을 펼쳤을 때 줄들: 사람이 봐야 할 것을 한곳에 모은다 (제목은 바깥 제목 줄이 가진다)
// 빠진 자료 줄: target `materials.missing[i]`의 그 줄 (올리기 버튼·보류 작업을 보이려고)
const missingOf = (item: ReviewItem, m: CaseMaterials | null) => {
  const i = /^materials\.missing\[(\d+)\]$/.exec(item.target)?.[1]
  return i === undefined ? undefined : m?.missing[Number(i)]
}

export function ReviewPanel({ items, r, materials, caseId }: Props) {
  const go = useTodoGo()
  const { openPage } = useContext(SourceContext)
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {items === null ? (
        <Space direction="vertical" size={4}>
          <StatusTag status="unverified" />
          <Typography.Text type="secondary">
            검토할 사항 목록을 받지 못했습니다 (모름). 정리 결과의 상태 꼬리표를 직접 보세요.
          </Typography.Text>
        </Space>
      ) : items.length === 0 ? (
        <Typography.Text type="secondary">검토할 사항 없음</Typography.Text>
      ) : (
        // 무엇을·왜·무엇을 확인할지 풀어 쓸 수 있는 줄 (정리 결과의 원문·쪽·떨어진 검사로). 같은 문장·같은 이유 청구항은 한 줄로
        mergeDetails(items.map((item) => ({ item, detail: reviewDetail(item, r) }))).map(({ item, detail }, i) => {
          const target = reviewTargetGo(item.target, r)
          const missing = item.kind === 'missing_material' ? missingOf(item, materials) : undefined
          if (detail)
            return (
              <div
                key={`${item.kind}-${item.target}-${i}`}
                style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '12px 0', borderBottom: '1px solid var(--line-neutral-tertiary)' }}
              >
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                  <KindTag item={item} />
                  <span className="body2" style={{ fontWeight: 600 }}>{detail.title}</span>
                </div>
                <span className="body2 t2">{detail.why}</span>
                {detail.raw && (
                  <span className="label1 t3" style={{ paddingLeft: 10, borderLeft: '2px solid var(--line-neutral-secondary)' }}>
                    통지서: “{detail.raw}”
                  </span>
                )}
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span className="body2" style={{ fontWeight: 600 }}>확인할 것</span>
                  <span className="body2">{detail.todo}</span>
                  {detail.page !== null && (
                    <Button size="small" onClick={() => openPage(detail.page, detail.raw)}>
                      통지서 {detail.page}쪽에서 보기
                    </Button>
                  )}
                  {target && (
                    <Button type="link" size="small" onClick={() => go(target)}>
                      {target.label}
                    </Button>
                  )}
                </div>
              </div>
            )
          return (
            <div
              key={`${item.kind}-${item.target}-${i}`}
              style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '12px 0', borderBottom: '1px solid var(--line-neutral-tertiary)' }}
            >
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                <KindTag item={item} />
                <span className="body2" style={{ fontWeight: 600, flex: '1 1 200px' }}>
                  {/* 서버가 조문 코드("29-1")만 줄 때는 "특허법 제29조제1항"으로 */}
                  {/^\d+(-\d+){0,2}$/.test(item.label) ? `특허법 ${articleLabel(item.label)}` : item.label}
                </span>
                <span className="label1 t3" style={{ flex: '1 1 200px' }}>
                  {reasonText(item.reason)}
                </span>
                {/* 빠진 자료는 이 자리에서 바로 올린다 (지원 안 하는 나라는 ask_upload가 false라 버튼 없음) */}
                {missing?.ask_upload && <UploadMaterialButton caseId={caseId} what={missing.what} />}
                {/* 줄을 누르면 그 카드로 (갈 자리를 모르는 줄은 버튼 없음) */}
                {target && (
                  <Button type="link" size="small" onClick={() => go(target)}>
                    {target.label}
                  </Button>
                )}
              </div>
              {/* 이 자료를 기다리며 멈춘 작업 (나머지 작업은 진행) */}
              {missing?.depends_on_tasks.map((t) => (
                <span key={t} className="label1 t3" style={{ paddingLeft: 4 }}>
                  → 보류: {heldTaskLabel(t)}
                </span>
              ))}
            </div>
          )
        })
      )}
      <StatusLegend />
    </div>
  )
}
