import { App, Alert, Button, Radio } from 'antd'
import { useContext, useState } from 'react'
import { Link, useLoaderData, useNavigate, useRevalidator, useRouteLoaderData } from 'react-router'
import { api } from '../../api'
import { AmendmentLimitAlert } from '../../components/CaseAlerts'
import { OriginTag } from '../../components/DirectionTags'
import { HumanCheckTag } from '../../components/Marks'
import { SourceContext } from '../../components/sourceContext'
import { StatusTag } from '../../components/StatusTag'
import { claimRange, claimsText, sentence } from '../../format'
import {
  addedSourceLabel,
  amendmentKindLabel,
  amendmentLimitLabel,
  confidenceLabel,
  rebuttalTypeLabel,
  rejectionKindLabel,
  sourceKindLabel,
} from '../../labels'
import type { DirectionsLoaderData, OALoaderData } from '../../loaders'
import type { Evidence1 } from '../../types/generated/ComparisonTable'
import type { DirectionCandidate, DirectionCandidates, DirectionSelection } from '../../types/generated/DirectionCandidates'
import type { JudgmentUnit } from '../../types/generated/JudgmentUnit'
import type { LegalEvidenceBundle, LegalSource } from '../../types/generated/LegalEvidenceBundle'

// 근거가 든 문서 종류 글자. 근거 위치(Evidence)에는 종류 칸이 없어 문서 번호 끝으로 읽는다 (못 읽으면 "근거")
function documentKind(documentId: string): string {
  if (/_spec$/.test(documentId)) return '명세서'
  if (/_claims$/.test(documentId)) return '청구항'
  const cite = /_D(\d+)$/.exec(documentId)
  if (cite) return `인용발명 ${cite[1]}`
  return '근거'
}

// 후보 근거가 법률 근거(색인 조각)와 같은 조각이면 그 법률 근거를 돌려준다. 조각 번호가 없으면 같다고 보지 않는다
function legalMatch(e: Evidence1, bundles: LegalEvidenceBundle[]): { source: LegalSource; checkedOn: string } | null {
  if (e.chunk_id === null) return null
  for (const b of bundles) {
    for (const c of b.claims) {
      const s = c.sources.find((x) => x.evidence.document_id === e.document_id && x.evidence.chunk_id === e.chunk_id)
      if (s) return { source: s, checkedOn: b.checked_on }
    }
  }
  return null
}

// 근거 N개: 줄마다 종류 라벨 · 링크 글 · (원문 글자를 못 받았으면) 확인되지 않음. 누르면 오른쪽 판에 연다
function BasisLines({ c, legal }: { c: DirectionCandidate; legal: LegalEvidenceBundle[] }) {
  const { openCite, openEvidence } = useContext(SourceContext)
  if (c.evidence.length === 0) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <span className="label2 t3" style={{ marginBottom: 4 }}>
        근거 {c.evidence.length}개 · 누르면 오른쪽에 원문
      </span>
      {c.evidence.map((e, i) => {
        const law = legalMatch(e, legal)
        const where = e.location ?? (e.page !== null ? `${e.page}쪽` : e.document_id)
        const kind = law ? sourceKindLabel[law.source.source_kind] : documentKind(e.document_id)
        return (
          <div
            key={`${e.document_id}-${e.location}-${i}`}
            style={{
              display: 'flex',
              gap: 12,
              alignItems: 'center',
              padding: '10px 0',
              borderBottom: '1px solid var(--line-neutral-tertiary)',
              flexWrap: 'wrap',
            }}
          >
            <span className="label1 t3" style={{ width: 88 }}>
              {kind}
            </span>
            <Button
              type="link"
              style={{ padding: 0, height: 'auto', textAlign: 'left', whiteSpace: 'normal' }}
              onClick={() =>
                law
                  ? openEvidence(law.source, law.checkedOn)
                  : openCite({ title: `${kind} ${where}`, items: [e], status: c.status, note: null })
              }
            >
              {e.raw_text ? `${e.raw_text} · ${where}` : where}
            </Button>
            {e.raw_text === null && <StatusTag status="unverified" detail={false} />}
          </div>
        )
      })}
    </div>
  )
}

// 작은 칸 하나: 위 작은 이름 + 아래 값
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span className="label2 t3">{label}</span>
      <span className="body2">{children}</span>
    </div>
  )
}

// 고른 후보의 칸들: 데이터에 있는 것만 (없는 칸은 그리지 않는다)
function Fields({ c }: { c: DirectionCandidate }) {
  const claims = [...new Set(c.amendment_core.map((a) => a.claim))]
  return (
    <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
      <Field label="보정 핵심">
        {c.amendment_core.length === 0
          ? '보정 없음'
          : c.amendment_core.map((a) => (
              <div key={`${a.claim}-${a.kind}`}>
                청구항 {a.claim}: {amendmentKindLabel[a.kind]}
                {a.source && ` (출처: ${addedSourceLabel[a.source]})`}
              </div>
            ))}
      </Field>
      {claims.length > 0 && <Field label="함께 바뀌는 청구항">청구항 {claimRange(claims)}</Field>}
      {c.per_rejection.length > 0 && (
        <Field label="거절이유별 대응">
          {c.per_rejection.map((r) => (
            <div key={r.rejection}>
              거절이유 {r.rejection}: {r.response}
            </div>
          ))}
        </Field>
      )}
      {c.rebuttal && (
        <Field label="반박 논리">
          {rebuttalTypeLabel[c.rebuttal.type]} — {c.rebuttal.summary}
        </Field>
      )}
      {c.checks.length > 0 && (
        <Field label="확인 사항">
          {c.checks.map((x) => (
            <div key={x}>{x}</div>
          ))}
        </Field>
      )}
    </div>
  )
}

const rankText = (c: DirectionCandidate) => (c.rank === null ? '순위 없음' : `${c.rank}순위`)

// 묶음 머리 작은 글: "묶음 1 · 진보성 · 청구항 1–5"
const unitHead = (u: JudgmentUnit | undefined, unitId: string) =>
  u ? `묶음 ${u.order} · ${rejectionKindLabel[u.rejection_kind]} · 청구항 ${claimRange(u.claims)}` : unitId

// 4 대응 방향: 묶음마다 고른 후보(AI 기본값 또는 직접 고름)를 크게, 근거·칸을 줄로, 다른 후보로 바꾸기.
// 최종 선택은 사람이 한다 (AI는 기본값만)
export function DirectionsPage() {
  const { units, directions, caseCheck } = useLoaderData() as DirectionsLoaderData
  const { oa, oaResult, legal } = useRouteLoaderData('oa') as OALoaderData
  const { message } = App.useApp()
  const revalidator = useRevalidator()
  const navigate = useNavigate()
  // 묶음마다 지금 선택 (처음엔 서버가 준 값: AI 기본값 또는 비어 있음)
  const [chosen, setChosen] = useState<Record<string, DirectionSelection | null>>(() =>
    Object.fromEntries(directions.map((d) => [d.unit_id, d.selection])),
  )
  // 저장 중인 묶음들 (여러 묶음을 빨리 골라도 서로 덮지 않게 묶음마다 따로)
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [checkOpen, setCheckOpen] = useState(false)

  // 사람이 고르면 서버에 저장한다 (저장한 선택은 1등과 같아도 "직접 고름")
  const choose = async (d: DirectionCandidates, candidateId: string) => {
    setSaving((prev) => ({ ...prev, [d.unit_id]: true }))
    try {
      const saved = await api.selectDirection(d.unit_id, candidateId)
      // 응답이 늦게 와도 다른 묶음의 선택을 덮지 않게 그때의 최신 값에 더한다
      setChosen((prev) => ({ ...prev, [d.unit_id]: saved.selection }))
      // 사건 틀의 "직접 할 일" 개수도 고른 묶음을 빼고 다시 센다
      revalidator.revalidate()
    } catch (e) {
      message.error(`저장하지 못했습니다: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving((prev) => ({ ...prev, [d.unit_id]: false }))
    }
  }

  // AI가 다루지 않은 거절이유: 사건 전체 검사와 정리 결과 양쪽에서 모은다 (번호가 정리 결과에 없어도 번호는 보인다)
  const rejections = oaResult?.result.rejections ?? []
  const unsupportedNos = [
    ...new Set([...(caseCheck?.unsupported_rejections ?? []), ...rejections.filter((r) => !r.supported).map((r) => r.no)]),
  ].sort((a, b) => a - b)
  const unsupportedText = unsupportedNos
    .map((no) => {
      const r = rejections.find((x) => x.no === no)
      return r ? `${no} (${claimsText(r.claims)})` : `${no}`
    })
    .join(', ')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <AmendmentLimitAlert noticeKind={oaResult?.result.notice_kind.value ?? null} />
      {directions.length === 0 && <span className="body2 t3">대응 방향 후보가 아직 없습니다</span>}
      {directions.map((d, idx) => {
        const sel = chosen[d.unit_id]
        const picked = d.candidates.find((c) => c.candidate_id === sel?.candidate_id)
        return (
          <div key={d.unit_id} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {idx > 0 && <hr className="hr" style={{ width: '100%', margin: 0 }} />}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span className="label1 t3">
                {unitHead(
                  units.find((u) => u.unit_id === d.unit_id),
                  d.unit_id,
                )}
              </span>
              {sel ? <OriginTag origin={sel.origin} /> : <HumanCheckTag>직접 판단 필요 · 초안 보류</HumanCheckTag>}
              {/* 보정 제한: 최초/최후. 모르면 값 없이 상태만 (없음으로 읽히지 않게) */}
              <span className="label1 t3">
                보정 제한: {d.amendment_limit.value ? amendmentLimitLabel[d.amendment_limit.value] : '확인되지 않음'}
              </span>
              {/* 값이 있어도 확인되지 않았으면(애매 등) 상태를 같이 보인다 */}
              {d.amendment_limit.status.value !== 'confirmed' && <StatusTag status={d.amendment_limit.status} />}
            </div>

            {picked ? (
              <>
                <h2 className="heading1" style={{ fontSize: 24, lineHeight: '32px' }}>
                  {picked.rank === null ? picked.name : `${rankText(picked)} · ${picked.name}`}
                </h2>
                <p className="body1 t2">
                  {sentence(picked.reason)} 확신도 {confidenceLabel[picked.confidence]}.
                </p>
                {picked.status.value !== 'confirmed' && (
                  <div>
                    <StatusTag status={picked.status} />
                  </div>
                )}
                <BasisLines c={picked} legal={legal.filter((b) => b.unit_id === d.unit_id || b.unit_id === null)} />
                <Fields c={picked} />
              </>
            ) : (
              <p className="body1 t2">
                확신도가 낮아 미리 고르지 않았어요. 후보 {d.candidates.length}개는 순위 없이 보여요. 고를 때까지 이 묶음의 초안은 보류해요.
              </p>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingTop: 8 }}>
              <span className="label1 t2">
                {picked ? '다른 후보로 바꾸기' : '후보 고르기'} · 순위는 검토 순서 제안이고 등록을 보증하지 않아요
              </span>
              <Radio.Group
                value={sel?.candidate_id ?? null}
                disabled={saving[d.unit_id] === true}
                onChange={(e) => choose(d, e.target.value as string)}
                options={d.candidates.map((c) => ({
                  label: `${c.rank === null ? '' : `${rankText(c)} `}${c.name} (확신도 ${confidenceLabel[c.confidence]})`,
                  value: c.candidate_id,
                }))}
                style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
              />
            </div>
          </div>
        )
      })}

      {unsupportedNos.length > 0 && (
        <Alert
          type="error"
          showIcon
          message={`AI가 다루지 않은 거절이유 ${unsupportedText}이 남아 있어요. 직접 대응해 주세요.`}
        />
      )}

      {/* 사건 전체 검사: 결과가 없으면 확인되지 않음, 있으면 접어 두고 경고·실패 개수만 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {caseCheck === null ? (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <StatusTag status="unverified" />
            <span className="label1 t3">사건 전체 검사 결과가 아직 없습니다</span>
          </div>
        ) : (
          <>
            <Button type="text" onClick={() => setCheckOpen(!checkOpen)} style={{ alignSelf: 'flex-start' }}>
              {`사건 전체 검사 ${caseCheck.items.length}항목 · 확인할 것 ${caseCheck.items.filter((i) => i.result !== 'ok').length}개 ${checkOpen ? '접기' : '보기'}`}
            </Button>
            {checkOpen &&
              caseCheck.items.map((it) => (
                <div key={it.name} style={{ display: 'flex', flexDirection: 'column', paddingLeft: 16, borderLeft: '2px solid var(--line-neutral-secondary)' }}>
                  <span className="body2">
                    <b>{it.name}</b> · {it.result === 'ok' ? '이상 없음' : it.result === 'warn' ? '확인 필요' : '실패'}
                  </span>
                  <span className="label1 t3">{it.detail}</span>
                </div>
              ))}
          </>
        )}
      </div>

      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
        {/* 초안 만들기 API는 v0에 없어서 지금은 초안 단계로 이동만 한다 */}
        <Button type="primary" size="large" onClick={() => navigate(`/oas/${oa.oa_id}/drafts`)}>
          고른 방향으로 초안 만들기
        </Button>
        <Link to={`/oas/${oa.oa_id}/compare`} className="label1">
          인용발명 대비로 돌아가기
        </Link>
      </div>
    </div>
  )
}
