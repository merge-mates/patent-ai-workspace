import { caseToCheck } from '../drafts/coverage'
import { App, Alert, Button, Input, Radio } from 'antd'
import { EmptyReason } from '../../components/EmptyReason'
import { useContext, useState } from 'react'
import { Link, useLoaderData, useNavigate, useRevalidator, useRouteLoaderData } from 'react-router'
import { api } from '../../api'
import { AmendmentLimitAlert } from '../../components/CaseAlerts'
import { OriginTag } from '../../components/DirectionTags'
import { HumanCheckTag, HumanTag } from '../../components/Marks'
import { SourceContext } from '../../components/sourceContext'
import { StatusLine } from '../../components/StatusLine'
import { StatusTag } from '../../components/StatusTag'
import { claimRange, claimsText, sentence, unsupportedRejectionNos } from '../../format'
import {
  addedSourceLabel,
  amendmentKindLabel,
  confidenceLabel,
  rebuttalTypeLabel,
  rejectionKindLabel,
  sourceKindLabel,
  waitingForLabel,
  LOW_CONFIDENCE_TEXT,
} from '../../labels'
import type { DirectionsLoaderData, OALoaderData } from '../../loaders'
import { getRunSnapshot, markSelectionRun } from '../../runPoll'
import { selectionErrorText } from '../../selectionError'
import type { LatestRun, SelectionBody } from '../../types/provisional/case'
import { useRunSnapshot } from '../../useRunSnapshot'
import type { Evidence1 } from '../../types/generated/ComparisonTable'
import type { DirectionCandidate, DirectionCandidates, DirectionSelection } from '../../types/generated/DirectionCandidates'
import type { JudgmentUnit } from '../../types/generated/JudgmentUnit'
import type { LegalEvidenceBundle, LegalSource } from '../../types/generated/LegalEvidenceBundle'

// 근거가 든 문서 이름: 같은 OA 대비표의 인용발명 이름(D1 등)과 문서 번호를 맞춘다. 통지서 문서면 "통지서".
// 못 맞추면 명세서·청구항(문서 번호 끝 글자)이고, 그래도 모르면 "근거"
function documentKind(documentId: string, names: Map<string, string>, noticeId: string | null): string {
  if (noticeId !== null && documentId === noticeId) return '통지서'
  const cite = names.get(documentId)
  if (cite) return cite
  if (/_spec$/.test(documentId)) return '명세서'
  if (/_claims$/.test(documentId)) return '청구항'
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
function BasisLines({
  c,
  legal,
  names,
  noticeId,
}: {
  c: DirectionCandidate
  legal: LegalEvidenceBundle[]
  names: Map<string, string>
  noticeId: string | null
}) {
  const { openCite, openEvidence, openPage } = useContext(SourceContext)
  if (c.evidence.length === 0) return null
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <span className="label2 t3" style={{ marginBottom: 4 }}>
        근거 {c.evidence.length}개 · 누르면 오른쪽에 원문
      </span>
      {c.evidence.map((e, i) => {
        const law = legalMatch(e, legal)
        const where = e.location ?? (e.page !== null ? `${e.page}쪽` : e.document_id)
        const kind = law ? sourceKindLabel[law.source.source_kind] : documentKind(e.document_id, names, noticeId)
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
              onClick={() => {
                if (law) openEvidence(law.source, law.checkedOn)
                // 통지서 근거는 받아 둔 통지서 원문을 그 쪽으로 연다
                else if (e.document_id === noticeId) openPage(e.page, e.raw_text)
                else openCite({ title: `${kind} ${where}`, items: [e], status: c.status, note: null })
              }}
            >
              {e.raw_text ? `${e.raw_text} · ${where}` : where}
            </Button>
            {e.raw_text === null && <span className="label2 t3">원문 글자 없음</span>}
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
// hideAmendment: 보정을 사건 전체에서 한 번 정했으면(사건 단위 보정안) 묶음별 보정 칸은 그리지 않는다.
// 묶음은 처음 분석하는 틀이고, 실제 보정은 초안의 보정 전략을 따른다
function Fields({ c, hideAmendment = false }: { c: DirectionCandidate; hideAmendment?: boolean }) {
  // 보정하는 청구항: 그대로(unchanged)인 청구항은 빼고 센다 (argue_only는 칸이 안 그려짐. F4 opinion.py has_amendment와 같은 기준)
  const claims = [...new Set(c.amendment_core.filter((a) => a.kind !== 'unchanged').map((a) => a.claim))]
  return (
    <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap' }}>
      {!hideAmendment && <Field label="보정 핵심">
        {c.amendment_core.length === 0
          ? '보정 없음'
          : c.amendment_core.map((a) => (
              <div key={`${a.claim}-${a.kind}`}>
                청구항 {a.claim}: {amendmentKindLabel[a.kind]}
                {a.source && ` (출처: ${addedSourceLabel[a.source]})`}
              </div>
            ))}
      </Field>}
      {!hideAmendment && claims.length > 0 && <Field label="보정하는 청구항">청구항 {claimRange(claims)}</Field>}
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
          {checkLines(c.checks).map((x) => (
            <div key={x}>{x}</div>
          ))}
        </Field>
      )}
    </div>
  )
}

// 확인 사항 줄 정리: "F3 보류: 청구항 N: 대표 청구항 …에 차이 후보·불명 구성요소가 있어 종속항을 대비하지 않음 …"이
// 종속항마다 반복되므로 한 줄로 묶고 쉬운 말로 바꾼다. 그 밖의 줄은 그대로
function checkLines(all: string[]): string[] {
  // "법률 근거: … 직접 검토 필요"는 묶음마다 늘 같은 줄이라 화면에서 뺀다 (재아 결정 11/27, 데이터에는 남음)
  const checks = all.filter((x) => !x.startsWith('법률 근거:'))
  const held = checks.filter((x) => x.startsWith('F3 보류:'))
  if (held.length === 0) return checks
  const claims = held.map((x) => /청구항 (\d+)/.exec(x)?.[1]).filter((n): n is string => n !== undefined)
  const rep = /대표 청구항 (\d+)/.exec(held[0])?.[1]
  const line =
    `청구항 ${claims.join(', ')}(종속항)은 따로 대비하지 않았어요` +
    (rep ? `: 대표 청구항 ${rep}에 차이점 후보가 남아 있어 그쪽을 먼저 봤어요.` : '.') +
    ' 필요하면 직접 확인해 주세요.'
  return [...checks.filter((x) => !x.startsWith('F3 보류:')), line]
}

const rankText = (c: DirectionCandidate) => (c.rank === null ? '순위 없음' : `${c.rank}순위`)

// 머리 작은 글: "진보성 · 청구항 1–5" ("묶음 N"은 팀 안 말이라 청구항 범위로 부른다)
const unitHead = (u: JudgmentUnit | undefined, unitId: string) =>
  u ? `${rejectionKindLabel[u.rejection_kind]} · 청구항 ${claimRange(u.claims)}` : unitId

// 4 대응 방향: 묶음마다 고른 후보(AI 기본값 또는 직접 고름)를 크게, 근거·칸을 줄로, 다른 후보로 바꾸기.
// 최종 선택은 사람이 한다 (AI는 기본값만)
export function DirectionsPage() {
  const { units, directions, comparisons, caseCheck, directionsEmptyReason, hasCasePlan } = useLoaderData() as DirectionsLoaderData
  const { oa, oaResult, legal } = useRouteLoaderData('oa') as OALoaderData
  const { message } = App.useApp()
  const revalidator = useRevalidator()
  const navigate = useNavigate()
  // 방금 고른 선택(PUT 응답 값)과 그 선택이 묶인 작은 실행의 run_id. 서버는 작은 실행이 끝날 때까지 GET의 selection을 옛 값으로 두므로
  // 화면의 선택(d.selection)은 loader 값이고, 이 값은 "그 실행이 지금 도는 동안만" "방금 고름 · 반영 중"으로 따로 보인다.
  // 그 실행이 succeeded면 loader가 새 선택을 주니 loader 값만 보이고, failed·cancelled면 서버는 선택을 버리므로 다시 고르라고 알린다.
  // 묶음별로 들고 있어 다른 묶음 값이 섞이지 않고, run_id가 달라진 실행에는 다시 보이지 않는다 (지우는 것은 다음 고르기가 덮을 때)
  const [justChosen, setJustChosen] = useState<Record<string, { selection: DirectionSelection; runId: string }>>({})
  // 그 OA의 최근 실행이 도는 동안은 못 고른다 (서버는 409 run_in_progress)
  const runSnap = useRunSnapshot(oa.latest_run)
  // 방금 PUT으로 받은 새 실행: revalidate가 끝나기 전에는 oa.latest_run이 아직 옛 실행이라, 그 사이에도 이 실행을 구독해 본다.
  // (구독은 useSyncExternalStore라 이 실행의 상태가 바뀌면 다시 그려진다. revalidate 뒤 latest_run이 같은 실행이 되면 같은 스냅숏이다)
  const [pendingRun, setPendingRun] = useState<LatestRun | null>(null)
  const pendingSnap = useRunSnapshot(pendingRun)
  const isBuildingState = (s: string | undefined) => s === 'queued' || s === 'running'
  // 그 선택이 묶인 실행의 스냅숏: 지금 latest_run이면 그것, 아직 아니면 방금 받은 새 실행.
  // 방금 받은 실행은 도는 동안(틈)만 쓴다: 끝나면 runPoll이 revalidate해 latest_run이 따라오고,
  // 그 뒤 다른 실행(다시 돌리기 등)으로 넘어가면 옛 작은 실행의 "반영 중"·"반영되지 않음"이 남지 않게 한다
  const snapOf = (runId: string) =>
    runSnap?.run.run_id === runId
      ? runSnap
      : pendingSnap?.run.run_id === runId && isBuildingState(pendingSnap.run.state)
        ? pendingSnap
        : null
  // 막기: 서버 ACTIVE_STATES(queued·running·waiting_for_human)와 같다. waiting_for_human에 고르면 서버가 409
  const blocked =
    isBuildingState(runSnap?.run.state) || runSnap?.run.state === 'waiting_for_human' || isBuildingState(pendingSnap?.run.state)
  // 초안을 만드는 중: 번호를 기다리는 동안은 만드는 중이 아니라서 따로 둔다 ("반영 중"·"만드는 중" 글에만 쓴다)
  const rebuilding = isBuildingState(runSnap?.run.state) || isBuildingState(pendingSnap?.run.state)
  // 지금 실행이 이 화면에서 고른 작은 실행인가 (그 밖의 실행: 다시 돌리기 등)
  const ownRun = runSnap?.fromSelection === true || (isBuildingState(pendingSnap?.run.state) && pendingSnap?.fromSelection === true)
  // 저장 중인 묶음들 (여러 묶음을 빨리 골라도 서로 덮지 않게 묶음마다 따로)
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  // 누르기 막기: 실행이 막는 동안 + 어느 묶음이든 저장(PUT)이 오가는 동안 (그 사이 다른 묶음을 누르면 서버가 409)
  const locked = blocked || Object.values(saving).some(Boolean)
  const [checkOpen, setCheckOpen] = useState(false)
  // 문서 번호 → 인용발명 이름 (대비표 줄의 근거와 citation 이름으로 맞춘다)
  const citeNames = new Map<string, string>()
  for (const t of comparisons)
    for (const r of t.rows) for (const e of r.evidence) if (!citeNames.has(e.document_id)) citeNames.set(e.document_id, r.citation)

  // 직접 쓰기: 글 칸을 펼친 묶음과 쓰는 중인 글 (묶음마다 따로)
  const [writing, setWriting] = useState<Record<string, string>>({})
  const closeWriting = (unitId: string) =>
    setWriting((prev) => Object.fromEntries(Object.entries(prev).filter(([k]) => k !== unitId)))

  // 사람이 고르거나 직접 쓰면 서버에 저장한다 (후보 하나 또는 직접 쓴 글 하나, 저장한 선택은 1등과 같아도 "직접 고름")
  const save = async (d: DirectionCandidates, body: SelectionBody): Promise<boolean> => {
    setSaving((prev) => ({ ...prev, [d.unit_id]: true }))
    try {
      const saved = await api.selectDirection(d.unit_id, body)
      // 응답이 늦게 와도 다른 묶음의 값을 덮지 않게 그때의 최신 값에 더한다 (응답 값만, 지어내지 않음)
      setJustChosen((prev) => ({ ...prev, [d.unit_id]: { selection: saved.selection, runId: saved.run_id } }))
      // 응답의 run_id는 초안만 다시 만드는 새 작은 실행: 폴링에 넣고 화면 데이터를 다시 받는다.
      // 다시 받은 OA의 latest_run이 그 실행이라 사건 틀이 구독하고, 끝나면 runPoll이 방향·초안을 다시 받게 한다
      // (사건 틀의 "직접 할 일" 개수는 실행이 끝나 loader가 새 선택을 받아야 줄어든다)
      markSelectionRun(saved.run_id) // 사건 머리·단계 막대도 읽는 곳에 "고르기로 시작한 작은 실행"으로 넣는다
      // revalidate가 끝나기 전 틈에도 이 실행을 보게 한다 (markSelectionRun이 queued로 넣어 둔 값)
      const seeded = getRunSnapshot(saved.run_id)
      if (seeded) setPendingRun(seeded.run)
      revalidator.revalidate()
      return true
    } catch (e) {
      message.error(`저장하지 못했습니다: ${selectionErrorText(e)}`)
      return false
    } finally {
      setSaving((prev) => ({ ...prev, [d.unit_id]: false }))
    }
  }
  const choose = (d: DirectionCandidates, candidateId: string) => void save(d, { candidate_id: candidateId })
  // 직접 쓴 글 저장: 빈 글은 보내지 않고 글로 알린다
  const saveWritten = async (d: DirectionCandidates) => {
    const text = (writing[d.unit_id] ?? '').trim()
    if (text === '') {
      message.warning('직접 쓸 방향 글을 입력해 주세요 (빈 글은 저장하지 않아요)')
      return
    }
    if (await save(d, { written_direction: text })) closeWriting(d.unit_id)
  }

  // AI가 다루지 않은 거절이유: 사건 전체 검사와 정리 결과 양쪽에서 모은다 (번호가 정리 결과에 없어도 번호는 보인다)
  const rejections = oaResult?.result.rejections ?? []
  const unsupportedNos = unsupportedRejectionNos(caseCheck?.unsupported_rejections, rejections)
  const unsupportedText = unsupportedNos
    .map((no) => {
      const r = rejections.find((x) => x.no === no)
      return r ? `${no} (${claimsText(r.claims)})` : `${no}`
    })
    .join(', ')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
      <AmendmentLimitAlert noticeKind={oaResult?.result.notice_kind.value ?? null} />
      {/* 서버는 작은 실행이 끝날 때까지 옛 선택을 돌려준다: 끝나면 고른 선택이 여기에 보인다 */}
      {blocked && (
        <Alert
          type="info"
          showIcon
          message={
            rebuilding
              ? ownRun
                ? '고른 방향으로 초안을 만드는 중이에요 · 끝나면 선택이 여기에 보여요'
                : '실행 중이라 지금은 고를 수 없어요 · 끝난 뒤 골라 주세요'
              : `${waitingForLabel(runSnap?.waitingFor ?? null)} 중이라 지금은 고를 수 없어요 · 입력하고 실행이 끝난 뒤 골라 주세요`
          }
        />
      )}
      {/* 보정은 묶음마다가 아니라 사건 전체에서 한 번 정한다: 묶음별 방향은 반박 논점을 고르는 데 쓴다 */}
      {hasCasePlan && directions.length > 0 && (
        <Alert
          type="info"
          showIcon
          message={
            <span>
              보정은 묶음마다가 아니라 사건 전체에서 한 번 정해요. 여기서 고르는 방향은 의견서의 반박 논점으로 쓰여요.{' '}
              <Link to="../drafts" relative="path">
                초안의 보정 전략 보기
              </Link>
            </span>
          }
        />
      )}
      {/* 빈 목록이면 서버가 준 이유를 (넘김·보류·확인되지 않음), 이유가 없으면 지금 글자 */}
      {directions.length === 0 &&
        (directionsEmptyReason ? (
          <EmptyReason what="대응 방향" reason={directionsEmptyReason} />
        ) : (
          <span className="body2 t3">대응 방향 후보가 아직 없습니다</span>
        ))}
      {directions.map((d, idx) => {
        const sel = d.selection
        const mine = justChosen[d.unit_id]
        const mineSnap = mine !== undefined ? snapOf(mine.runId) : null // 그 선택이 묶인 실행 (아직 latest_run이 아니어도 찾는다)
        const live = mine !== undefined && mineSnap !== null
        const mineState = mineSnap?.run.state
        const just = live && isBuildingState(mineState) ? mine.selection : undefined
        const dropped = live && (mineState === 'failed' || mineState === 'cancelled') // 서버가 선택을 버린 경우
        const justName = d.candidates.find((c) => c.candidate_id === just?.candidate_id)?.name
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
              {just && (
                <HumanTag>
                  {just.written_direction !== null ? '방금 씀 · 반영 중' : `방금 고름 · 반영 중${justName ? `: ${justName}` : ''}`}
                </HumanTag>
              )}
              {dropped && <span className="label2" style={{ color: 'var(--fg-negative-text)' }}>고른 방향이 반영되지 않았어요 · 다시 골라 주세요</span>}
              {sel ? (
                <OriginTag origin={sel.origin} />
              ) : d.candidates.length === 0 ? (
                <StatusLine status={d.status} />
              ) : (
                <HumanCheckTag>{LOW_CONFIDENCE_TEXT} · 고를 때까지 초안 없음</HumanCheckTag>
              )}
              {/* 보정 제한: 최초/최후. 모르면 값 없이 상태 꼬리표만 (없음으로 읽히지 않게, 글자는 한 번만) */}
              <span className="label1 t3">
                {/* "보정 제한: 최초"는 뜻이 안 읽혀 보정할 수 있는 범위로 풀어 쓴다 */}
                {d.amendment_limit.value === 'initial'
                  ? '보정 범위: 최초 명세서 범위 안 (최초거절이유통지)'
                  : d.amendment_limit.value === 'final'
                    ? '보정 범위: 제47조제3항 제한 (최후거절이유통지)'
                    : '보정 범위'}
              </span>
              {/* 값이 있어도 확인되지 않았으면(애매 등) 상태를 같이 보인다 */}
              {d.amendment_limit.status.value !== 'confirmed' && <StatusTag status={d.amendment_limit.status} />}
            </div>

            {sel?.written_direction ? (
              // 직접 쓴 방향: AI 후보와 섞지 않고 쓴 글만 보인다 (어느 후보도 고르지 않은 상태)
              <>
                <h2 className="heading1" style={{ fontSize: 24, lineHeight: '32px' }}>직접 쓴 방향</h2>
                <p className="body1" style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{sel.written_direction}</p>
                <span className="label2 t3">직접 쓴 방향이라 AI가 이 묶음의 초안을 만들지 않아요. 직접 대응해 주세요.</span>
              </>
            ) : picked ? (
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
                <BasisLines
                  c={picked}
                  legal={legal.filter((b) => b.unit_id === d.unit_id || b.unit_id === null)}
                  names={citeNames}
                  noticeId={oa.document_id}
                />
                <Fields c={picked} hideAmendment={hasCasePlan} />
              </>
            ) : d.candidates.length === 0 ? (
              // 후보가 0개면 실패한 것이다 (이유는 머리의 상태 꼬리표). 확신이 낮아서라고 말하지 않는다
              <Alert type="warning" showIcon message="후보를 만들지 못했어요. 이 묶음은 직접 대응해 주세요." />
            ) : d.flags.includes('needs_human_judgment') && !d.candidates.some((c) => c.rank !== null) ? (
              <p className="body1 t2">
                확신도가 낮아 미리 고르지 않았어요. 후보 {d.candidates.length}개는 순위 없이 보여요. 고를 때까지 이 묶음의 초안은 만들지 않아요.
              </p>
            ) : (
              <p className="body1 t2">아직 고르지 않았어요. 후보를 골라 주세요. 고를 때까지 이 묶음의 초안은 만들지 않아요.</p>
            )}

            {d.candidates.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingTop: 8 }}>
              <span className="label1 t2">
                {picked ? '다른 후보로 바꾸기' : '후보 고르기'} · 순위는 검토 순서 제안이고 등록을 보증하지 않아요
              </span>
              <Radio.Group
                value={just ? just.candidate_id : (sel?.candidate_id ?? null)}
                disabled={locked}
                onChange={(e) => choose(d, e.target.value as string)}
                options={d.candidates.map((c) => ({
                  label: (
                    <span>
                      {`${c.rank === null ? '' : `${rankText(c)} `}${c.name} (확신도 ${confidenceLabel[c.confidence]})`}{' '}
                      {/* 순위 있는 후보와 섞여 있어도 확신이 낮은 후보는 직접 판단 필요 (ADR 0001) */}
                      {c.confidence === 'low' && <HumanCheckTag>{LOW_CONFIDENCE_TEXT}</HumanCheckTag>}
                    </span>
                  ),
                  value: c.candidate_id,
                }))}
                style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
              />
            </div>
            )}

            {/* 직접 쓰기: 모든 묶음에 둔다. 아직 안 골랐고 확신이 낮은 묶음은 눈에 띄게(primary) */}
            {writing[d.unit_id] === undefined ? (
              <div>
                <Button
                  type={!sel && !just && d.flags.includes('needs_human_judgment') ? 'primary' : 'default'}
                  disabled={locked}
                  onClick={() => setWriting((prev) => ({ ...prev, [d.unit_id]: sel?.written_direction ?? '' }))}
                >
                  직접 쓰기
                </Button>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <span className="label1 t2">후보 밖 방향을 직접 써요. 저장하면 AI는 이 묶음의 초안을 만들지 않아요</span>
                <Input.TextArea
                  autoSize={{ minRows: 3, maxRows: 10 }}
                  value={writing[d.unit_id]}
                  onChange={(e) => setWriting((prev) => ({ ...prev, [d.unit_id]: e.target.value }))}
                />
                <div style={{ display: 'flex', gap: 8 }}>
                  <Button type="primary" size="small" loading={saving[d.unit_id] === true} disabled={locked && saving[d.unit_id] !== true} onClick={() => void saveWritten(d)}>
                    저장
                  </Button>
                  <Button size="small" onClick={() => closeWriting(d.unit_id)}>
                    취소
                  </Button>
                </div>
              </div>
            )}
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
              {/* AI가 아직 검사하지 않는 규칙은 "확인할 것" 개수에서 뺀다 (펼치면 그대로 보임) */}
              {`사건 전체 검사 ${caseCheck.items.length}항목 · 확인할 것 ${caseToCheck(caseCheck.items).length}개 ${checkOpen ? '접기' : '보기'}`}
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
        {/* 방향을 고르면 서버가 바로 초안을 다시 만든다: 이 버튼은 초안 단계로 이동만 한다 */}
        <Button type="primary" size="large" onClick={() => navigate(`/oas/${oa.oa_id}/drafts`)}>
          초안 보기
        </Button>
        <Link to={`/oas/${oa.oa_id}/compare`} className="label1">
          인용발명 대비로 돌아가기
        </Link>
      </div>
    </div>
  )
}
