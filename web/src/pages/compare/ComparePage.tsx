import { Button, Empty, Result, Segmented } from 'antd'
import { useLoaderData, useNavigate, useRouteLoaderData, useSearchParams, Link } from 'react-router'
import { API_MODE } from '../../api'
import { HumanCheckTag } from '../../components/Marks'
import { isRunEnded } from '../../runPoll'
import { useRunSnapshot } from '../../useRunSnapshot'
import { StatusTag } from '../../components/StatusTag'
import { claimRange } from '../../format'
import { articleLabel, COMPARE_UNVERIFIED_TEXT, rejectionKindLabel } from '../../labels'
import type { CompareLoaderData, OALoaderData } from '../../loaders'
import type { JudgmentUnit } from '../../types/generated/JudgmentUnit'
import { ClarityView } from './ClarityView'
import { ComparisonView } from './ComparisonView'

// 판단 단위(묶음) 이름: "거절이유 1 · 진보성". 같은 거절이유에 묶음이 둘 이상이면 대표 청구항으로 가른다
const unitLabel = (u: JudgmentUnit, all: JudgmentUnit[]) =>
  `거절이유 ${u.rejection} · ${rejectionKindLabel[u.rejection_kind]}${
    all.filter((x) => x.rejection === u.rejection).length > 1 ? ` · 청구항 ${u.representative_claim}` : ''
  }`

// 3 인용발명 대비: 묶음을 고르면 그 묶음의 핵심(AI 제안) → 구성요소 표(또는 명확성 줄) → 대응 방향으로
export function ComparePage() {
  const { units, comparisons, clarity, legal } = useLoaderData() as CompareLoaderData
  const { oa, oaResult, ready } = useRouteLoaderData('oa') as OALoaderData
  const navigate = useNavigate()
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
      <span className="label1 t2">{`거절이유 ${r.no}(특허법 ${articleLabel(r.article.value)})는 AI가 다루지 않아 판단 단위가 없어요.`}</span>
    </div>
  ))

  if (!unit) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {unsupportedRows}
        <Empty
          description={
            API_MODE === 'mock'
              ? '판단 단위가 없습니다 (예시 데이터는 fixture 사건 셋에만 있음)'
              : '판단 단위가 없습니다 (AI가 다루는 거절이유가 없음)'
          }
        />
      </div>
    )
  }
  const table = comparisons.find((t) => t.unit_id === unit.unit_id)
  const review = clarity.find((c) => c.unit_id === unit.unit_id)
  // 법리는 정리 단계 거절이유 줄 안에 있다. 그 거절이유에 법률 근거 묶음이 있을 때만 링크
  const hasLaw = legal.some((b) => b.rejection === unit.rejection)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
      {unsupportedRows}
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
          묶음 {unit.order} · 청구항 {claimRange(unit.claims)}
          {unit.read_with.length > 0 ? ` · 함께 읽을 청구항 ${claimRange(unit.read_with)}` : ''}
        </span>
        {unit.status.value !== 'confirmed' && <StatusTag status={unit.status} detail={false} unverifiedText={COMPARE_UNVERIFIED_TEXT} />}
      </div>

      {table && <ComparisonView t={table} />}
      {review && <ClarityView c={review} unit={unit} />}
      {!table && !review && <Empty description="이 묶음의 대비 결과가 아직 없습니다" />}

      {hasLaw && (
        <Link to={`/oas/${oa.oa_id}#rejection-${unit.rejection}`} className="label1">
          이 거절이유의 법리 보기
        </Link>
      )}
      <div>
        <Button type="primary" size="large" disabled={!ready.directions} onClick={() => navigate(`/oas/${oa.oa_id}/directions`)}>
          {/* 결과가 없을 때 왜 못 가는지 글자로 (실행 중 / 멈춤·취소 / 모름) */}
          {ready.directions ? '대응 방향으로' : running ? '실행이 끝나면 열려요' : '대응 방향 결과가 없어요'}
        </Button>
      </div>
    </div>
  )
}
