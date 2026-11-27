import { Button, Empty, Result, Segmented } from 'antd'
import { useLoaderData, useNavigate, useRouteLoaderData, useSearchParams } from 'react-router'
import { API_MODE } from '../../api'
import { EmptyReason } from '../../components/EmptyReason'
import { HumanCheckTag } from '../../components/Marks'
import { RejectionLaw } from '../../components/RejectionLaw'
import { NextStep } from '../../components/NextStep'
import { SourceContext } from '../../components/sourceContext'
import { useContext } from 'react'
import { isRunEnded } from '../../runPoll'
import { useRunSnapshot } from '../../useRunSnapshot'
import { StatusTag } from '../../components/StatusTag'
import { claimRange, josaAfterNumber } from '../../format'
import { articleLabel, COMPARE_UNVERIFIED_TEXT, rejectionKindLabel } from '../../labels'
import type { CompareLoaderData, OALoaderData } from '../../loaders'
import type { JudgmentUnit } from '../../types/generated/JudgmentUnit'
import { ClarityView } from './ClarityView'
import { ComparisonView } from './ComparisonView'

// 판단 단위(묶음) 이름: "거절이유 1 · 진보성". 같은 거절이유에 묶음이 둘 이상이면 대표 청구항으로 가른다.
// 모든 묶음이 같은 거절이유면(명확성 사건에서 청구항마다 10개 등) 앞말을 빼고 "청구항 N"만 (탭이 길게 반복되지 않게)
const unitLabel = (u: JudgmentUnit, all: JudgmentUnit[]) => {
  const same = all.filter((x) => x.rejection === u.rejection).length
  if (same > 1 && same === all.length) return `청구항 ${u.representative_claim}`
  return `거절이유 ${u.rejection} · ${rejectionKindLabel[u.rejection_kind]}${same > 1 ? ` · 청구항 ${u.representative_claim}` : ''}`
}

// 3 인용발명 대비: 묶음을 고르면 그 묶음의 핵심(AI 제안) → 구성요소 표(또는 명확성 줄) → 대응 방향으로
export function ComparePage() {
  const { units, comparisons, clarity, legal, emptyReasons } = useLoaderData() as CompareLoaderData
  const { oa, oaResult, ready } = useRouteLoaderData('oa') as OALoaderData
  const navigate = useNavigate()
  const { openPage } = useContext(SourceContext)
  // 실행 중이면 대응 방향 결과가 아직 없을 수 있다 (없는 화면을 열면 result_not_ready 오류가 뜨던 곳)
  const run = useRunSnapshot(oa.latest_run)?.run ?? null
  const running = run !== null && !isRunEnded(run.state)
  // 고른 묶음은 주소(?unit=)에 둔다: 새로고침·다시 열기 뒤에도 같은 묶음
  const [params, setParams] = useSearchParams()

  if (units === null) {
    return <Result status="info" title="판단 단위가 아직 없습니다" subTitle="실행이 끝나면 여기에 대비와 근거가 보입니다" />
  }
  const unit = units.find((u) => u.unit_id === params.get('unit')) ?? units[0]
  const unsupported = oaResult?.result.rejections.filter((r) => !r.supported) ?? []

  // AI가 다루지 않는 거절이유: 판단 단위가 없으니 노란 직접 검토 줄로 알린다
  const unsupportedRows = unsupported.map((r) => (
    <div key={r.no} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <HumanCheckTag>직접 검토 필요</HumanCheckTag>
      <span className="label1 t2">{`거절이유 ${r.no}(특허법 ${articleLabel(r.article.value)}) — AI가 다루지 않는 거절이유라 대비하지 않았어요. 직접 검토해 주세요.`}</span>
    </div>
  ))

  if (!unit) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {unsupportedRows}
        {/* 서버가 빈 이유를 주면 그 이유를 (넘김·보류·확인되지 않음), 없으면 지금 글자 */}
        {emptyReasons.units ? (
          <EmptyReason what="판단 단위" reason={emptyReasons.units} />
        ) : (
          <Empty
            description={
              API_MODE === 'mock'
                ? '판단 단위가 없습니다 (예시 데이터는 fixture 사건 셋에만 있음)'
                : '판단 단위가 없습니다 (AI가 다루는 거절이유가 없음)'
            }
          />
        )}
      </div>
    )
  }
  const table = comparisons.find((t) => t.unit_id === unit.unit_id)
  const review = clarity.find((c) => c.unit_id === unit.unit_id)
  const unitReason = unit.rejection_kind === 'clarity' ? emptyReasons.clarity : emptyReasons.comparisons
  // 명확성 대표 청구항의 통지서 줄 (판단 원문·쪽): 검토가 없을 때 원문으로 보낸다
  const clarityRow =
    oaResult?.result.claim_rows.find((r) => r.rejection === unit.rejection && r.claim === unit.representative_claim) ?? null
  // 함께 읽을 앞 청구항(인용하는 청구항)의 검토가 있는 묶음: 명확성 종속항이 따를 곳
  const sameReasonUnit = units.find(
    (u) => u.unit_id !== unit.unit_id && unit.read_with.includes(u.representative_claim) && clarity.some((c) => c.unit_id === u.unit_id),
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
      {/* 좁은 화면에서는 이 줄만 옆으로 밀린다 */}
      <div style={{ overflowX: 'auto' }}>
        <Segmented
          value={unit.unit_id}
          onChange={(v) => setParams({ unit: v })}
          options={units.map((u) => ({ label: unitLabel(u, units), value: u.unit_id }))}
        />
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="label1 t3">
          {/* "묶음 N" 대신 청구항 범위만 */}
          청구항 {claimRange(unit.claims)}
          {unit.read_with.length > 0 ? ` · 함께 읽을 청구항 ${claimRange(unit.read_with)}` : ''}
        </span>
        {unit.status.value !== 'confirmed' && <StatusTag status={unit.status} detail={false} unverifiedText={COMPARE_UNVERIFIED_TEXT} />}
      </div>

      {table && <ComparisonView t={table} oa={oaResult?.result ?? null} unit={unit} />}
      {review && <ClarityView c={review} unit={unit} />}
      {/* 이 묶음에 맞는 목록(명확성 묶음은 명확성 문구 검토, 그 밖은 인용발명 대비)이 통째로 비었으면 서버가 준 이유를,
          목록은 있는데 이 묶음 줄만 없으면 지금 글자 */}
      {/* 명확성 종속항: 앞 청구항과 같은 이유라 따로 검토가 없다. "결과 없음" 대신 그 청구항 검토로 보낸다 */}
      {!table && !review && unit.rejection_kind === 'clarity' && sameReasonUnit && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="body1 t2">
            {`${josaAfterNumber(`청구항 ${unit.representative_claim}`, '은', '는')} ${josaAfterNumber(`청구항 ${claimRange(unit.read_with)}`, '을', '를')} 인용해 같은 이유로 지적됐어요. 따로 검토하지 않고 청구항 ${sameReasonUnit.representative_claim} 검토를 따라요.`}
          </span>
          <Button size="small" onClick={() => setParams({ unit: sameReasonUnit.unit_id })}>
            청구항 {sameReasonUnit.representative_claim} 검토 보기
          </Button>
        </div>
      )}
      {/* 명확성인데 검토가 없고 따를 앞 청구항도 없음: 통지서가 문제 표현을 따옴표로 짚지 않은 경우가 대부분이다.
          "해당 거절이유 없음"처럼 읽히지 않게 이유와 원문을 보인다 */}
      {!table && !review && unit.rejection_kind === 'clarity' && !sameReasonUnit && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <span className="body1 t2">
            {`${josaAfterNumber(`청구항 ${unit.representative_claim}`, '은', '는')} 통지서가 문제 표현을 따옴표로 짚지 않아 문구 검토를 하지 않았어요. 심사관 판단 원문을 직접 확인해 주세요.`}
          </span>
          {clarityRow && (
            <div>
              <Button size="small" onClick={() => openPage(clarityRow.page, clarityRow.raw_text)}>
                통지서에서 심사관 판단 보기{clarityRow.page !== null ? ` (${clarityRow.page}쪽)` : ''}
              </Button>
            </div>
          )}
          <NextStep title="따옴표 없는 명확성 지적도 검토">
            표현을 따옴표로 짚지 않고 "어느 단계와 결합하는지 알 수 없다"처럼 쓴 지적도, 심사관 판단 문장에서 문제 부분을 찾아 청구항과 대조해 보여요.
          </NextStep>
        </div>
      )}
      {!table && !review && !(unit.rejection_kind === 'clarity') && (unitReason ? (
        <EmptyReason what="인용발명 대비" reason={unitReason} />
      ) : (
        <Empty description="이 청구항들의 대비 결과가 아직 없습니다" />
      ))}
      {/* 법률 근거 목록이 비었으면 이유를 (예: F2 넘김) */}
      {emptyReasons.legal && <EmptyReason what="법률 근거" reason={emptyReasons.legal} />}

      {/* 이 거절이유의 법리: 정리 단계로 돌아가지 않고 이 자리에서 본다 (줄을 누르면 오른쪽 판에 근거 글) */}
      <RejectionLaw rejection={unit.rejection} legal={legal} />
      {/* AI가 다루지 않는 거절이유(기타)는 다루는 것 아래에 */}
      {unsupportedRows}
      <div>
        <Button type="primary" size="large" disabled={!ready.directions} onClick={() => navigate(`/oas/${oa.oa_id}/directions`)}>
          {/* 결과가 없을 때 왜 못 가는지 글자로 (실행 중 / 멈춤·취소 / 모름) */}
          {ready.directions ? '대응 방향으로' : running ? '실행이 끝나면 열려요' : '대응 방향 결과가 없어요'}
        </Button>
      </div>
    </div>
  )
}
