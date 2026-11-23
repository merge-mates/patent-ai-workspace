import { Alert, App, Button, Input, Segmented, Space, Tooltip, Typography } from 'antd'
import { EmptyReason } from '../../components/EmptyReason'
import { useContext, useState } from 'react'
import { Link, useLoaderData, useRouteLoaderData } from 'react-router'
import { api, API_MODE } from '../../api'
import { AiTag, HumanTag } from '../../components/Marks'
import { SourceContext } from '../../components/sourceContext'
import { TrackedText } from '../../components/TrackedText'
import type { DraftsLoaderData, OALoaderData } from '../../loaders'
import { unsupportedRejectionNos } from '../../format'
import { LOW_CONFIDENCE_TEXT, rejectionKindLabel } from '../../labels'
import { useRunSnapshot } from '../../useRunSnapshot'
import type { AmendedClaim, Evidence1 } from '../../types/generated/Drafts'
import type { DraftPatch, DraftsWithCheck } from '../../types/provisional/pending'
import { CoverageTable } from './CoverageTable'
import { buildCoverage, buildFixes, caseToCheck } from './coverage'
import { FixList } from './FixList'

// 고치는 중인 곳: 의견서 칸 하나 또는 보정 청구항 하나 (보낼 요청과 같은 모양)
type Editing = DraftPatch | null

// 초안이 바탕으로 삼은 선택과 지금 선택을 견준 결과
// - changed: 다른 후보를 골랐음 → 이 초안은 이전 방향으로 만든 것
// - picked: 보류였던 묶음에서 이제 방향을 골랐음 → 다시 돌려야 초안이 생김
// - written: 지금 선택이 직접 쓴 방향 → 서버는 그 묶음의 초안을 보류한다 (AI가 만들지 않음)
type BasisNote = 'changed' | 'picked' | 'written' | null

const humanTag = <HumanTag>직접 고침</HumanTag>

// 글 속 식별번호([0041] 등)를 링크로: 근거 목록에 같은 위치가 있으면 원문 판에 열고, 없으면 그냥 글자로 둔다
function LinkedText({ text, evidence, onOpen }: { text: string; evidence: Evidence1[]; onOpen: (token: string, e: Evidence1) => void }) {
  return (
    <>
      {text.split(/(\[\d{4}\])/).map((part, i) => {
        const e = /^\[\d{4}\]$/.test(part) ? evidence.find((x) => x.location === part) : undefined
        if (!e) return <span key={i}>{part}</span>
        return (
          <Typography.Link
            key={i}
            onClick={(ev) => {
              ev.stopPropagation() // 글을 눌러 고치는 동작과 겹치지 않게
              onOpen(part, e)
            }}
          >
            {part}
          </Typography.Link>
        )
      })}
    </>
  )
}

// 청구항이 어떻게 바뀌었나: 지운 글만 남으면 삭제, 같으면 그대로
function claimKind(before: string, text: string): '보정' | '삭제' | '그대로' {
  if (text.trim() === '') return '삭제'
  return text === before ? '그대로' : '보정'
}

// 5 초안 단계: 대응 현황 표 → 제출 전에 고칠 곳 → 초안 본문(의견서 / 보정 청구항)
export function DraftsPage() {
  const { drafts: initial, directions, caseCheck, draftsEmptyReason } = useLoaderData() as DraftsLoaderData
  const { oaResult, oa } = useRouteLoaderData('oa') as OALoaderData
  // 그 OA의 최근 실행이 아직 도는 동안 보이는 초안은 옛것이다 (방향을 고르면 초안만 다시 만드는 작은 실행이 생긴다)
  const runState = useRunSnapshot(oa.latest_run)?.run.state
  const rebuilding = runState === 'queued' || runState === 'running'
  const { message } = App.useApp()
  const { openCite } = useContext(SourceContext)
  const [drafts, setDrafts] = useState<DraftsWithCheck | null>(initial)
  const [view, setView] = useState<'opinion' | 'claims'>('opinion')
  const [aiShown, setAiShown] = useState<string[]>([]) // AI 원문을 펼친 칸: 's:<key>' / 'c:<청구항>'
  const [editing, setEditing] = useState<Editing>(null)
  // loader가 "다른 초안"을 받으면(작은 실행이 끝나 새 초안이 옴) 화면 state를 새로 시작한다 (렌더 중 이전 값과 비교).
  // 객체 참조로 비교하면 단계 전환 revalidate마다 새 객체가 와 고치던 글이 지워지므로, 초안 id와 바탕 선택으로 비교한다
  const initialKey = initial === null ? null : `${initial.draft_id}|${JSON.stringify(initial.based_on)}`
  const [seenKey, setSeenKey] = useState(initialKey)
  if (seenKey !== initialKey) {
    setSeenKey(initialKey)
    setDrafts(initial)
    setEditing(null)
    setAiShown([])
  }

  if (drafts === null) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {rebuilding && <Alert type="info" showIcon message="초안 만드는 중 · 끝나면 초안이 여기에 보여요" />}
        <h2 className="heading2">대응 현황 · 거절이유 × 청구항</h2>
        <span className="body1 t2">초안이 아직 없어 대응 현황을 셀 수 없어요</span>
        {/* 실행이 끝났는데 초안이 없으면 서버가 준 이유 (모든 묶음 보류·F4 넘김 등) */}
        {draftsEmptyReason && <EmptyReason what="초안" reason={draftsEmptyReason} />}
        {API_MODE === 'mock' && <span className="label2 t3">예시 초안은 '가상의 영상 처리 장치' 사건에만 있어요</span>}
      </div>
    )
  }

  const rejections = oaResult?.result.rejections ?? []
  // AI가 다루지 않은 거절이유: 사건 전체 검사 + 정리 결과의 supported=false
  const unsupported = unsupportedRejectionNos(caseCheck?.unsupported_rejections, rejections)
  const coverage = buildCoverage(drafts, directions, rejections, unsupported)
  const fixes = buildFixes(drafts, directions, rejections, unsupported, drafts.opinion.map((x) => x.title))
  const caseItems = caseToCheck(caseCheck?.items ?? [])

  // 고친 글을 저장한다. AI 원본(ai_text)은 서버가 그대로 남기고 사람 글은 human_text에 둔다
  const save = async () => {
    if (!editing) return
    try {
      setDrafts(await api.patchDraft(drafts.draft_id, editing))
      setEditing(null)
    } catch (e) {
      message.error(`저장하지 못했습니다: ${e instanceof Error ? e.message : String(e)}`)
    }
  }
  const toggleAi = (k: string) => setAiShown(aiShown.includes(k) ? aiShown.filter((x) => x !== k) : [...aiShown, k])

  const editor = (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      <Input.TextArea
        autoSize={{ minRows: 3, maxRows: 10 }}
        value={editing?.text}
        onChange={(e) => editing && setEditing({ ...editing, text: e.target.value })}
      />
      <Space>
        <Button size="small" type="primary" onClick={save}>
          저장
        </Button>
        <Button size="small" onClick={() => setEditing(null)}>
          취소
        </Button>
      </Space>
    </Space>
  )

  // 묶음마다 지금 선택과 초안의 바탕 선택을 견준다
  const noteOf = (unitId: string): BasisNote => {
    const sel = directions.find((d) => d.unit_id === unitId)?.selection
    if (sel?.origin === 'human_written') return 'written'
    const now = sel?.candidate_id ?? null
    const basis = drafts.based_on.find((b) => b.unit_id === unitId)?.candidate_id ?? null
    if (basis === null) return now === null ? null : 'picked'
    return now !== basis ? 'changed' : null
  }
  // 묶음 선택 출처: 고른 묶음 중 사람이 고른 것이 있나
  const picked = directions.flatMap((d) => (d.selection ? [d.selection] : []))
  const humanPicked = picked.filter((s) => s.origin === 'human_selected' || s.origin === 'human_edited' || s.origin === 'human_written').length
  // 직접 쓴 묶음이 있으면 "고름·씀"으로 구분한다
  const hasWritten = picked.some((s) => s.origin === 'human_written')
  const humanWord = hasWritten ? '직접 고름·씀' : '직접 고름'
  const pickSource = humanPicked === 0 ? 'AI 기본값' : humanPicked === picked.length ? humanWord : `일부 ${humanWord}`

  // 근거 링크는 의견서·보정 청구항 근거 목록에서 같은 위치를 찾아 원문 판으로
  const allEvidence = [...drafts.evidence, ...drafts.claims.flatMap((c) => c.spec_basis)]
  const openBasis = (token: string, e: Evidence1) =>
    openCite({ title: `최초 명세서 ${token}`, items: [e], status: drafts.status, note: null })

  const claimView = (c: AmendedClaim) => {
    const key = `c:${c.claim}`
    const isEditing = editing?.claim === c.claim
    // 어느 거절이유 대응인지: 정리 결과의 대상 청구항으로 찾는다
    const resp = rejections.filter((r) => r.claims.value?.includes(c.claim))
    const respText = resp.length
      ? `거절이유 ${resp.map((r) => `${r.no}(${rejectionKindLabel[r.kind]})`).join(', ')} 대응`
      : null
    const note = noteOf(c.unit_id)
    const head = (label: string, extra?: React.ReactNode) => (
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <h3 className="headline1" style={{ margin: 0 }}>{`청구항 ${c.claim} · ${label}`}</h3>
        {extra}
      </div>
    )
    const box = { display: 'flex', flexDirection: 'column', gap: 6, paddingBottom: 16, borderBottom: '1px solid var(--line-neutral-tertiary)' } as const
    // 보류: 사람이 방향을 고를 때까지 초안을 만들지 않는다
    if (c.ai_text === null) {
      return (
        <div key={c.claim} style={box}>
          {head(LOW_CONFIDENCE_TEXT)}
          {note === 'written' ? (
            <Alert
              type="info"
              showIcon
              message="직접 쓴 방향이라 AI가 초안을 만들지 않아요 · 직접 대응해 주세요"
              description={rebuilding ? '실행이 끝나면 이 묶음이 보류로 바뀌어요' : undefined}
            />
          ) : note === 'picked' ? (
            <Alert
              type="info"
              showIcon
              message={
                rebuilding
                  ? '고른 방향으로 초안을 만드는 중 · 끝나면 보여요'
                  : '방향을 골랐어요. 이 묶음의 초안은 아직 없어요 · 다시 만들어야 함'
              }
              description={
                API_MODE === 'mock'
                  ? 'mock은 초안을 새로 만들지 못해 이 묶음의 초안이 예시에 없는 채로 보여요.'
                  : undefined
              }
            />
          ) : (
            <Space wrap>
              <span className="body1" style={{ fontWeight: 600 }}>직접 판단 필요: 방향을 고르면 초안을 만들어요</span>
              <Link to="../directions" relative="path">
                <Button size="small">고르기</Button>
              </Link>
            </Space>
          )}
          {/* 서버는 지금 직접 쓴 묶음에도 일반 보류 글("방향을 고르면 초안을 만듭니다")을 줌 (서버 고침은 따로).
              두 글이 어긋나 보이지 않게 직접 쓴 묶음은 서버 글을 보이지 않는다 */}
          {c.held_reason && note !== 'written' && <span className="label2 t3">{c.held_reason}</span>}
        </div>
      )
    }
    const edited = c.human_text !== null
    const showAi = aiShown.includes(key)
    const text = edited && !showAi ? c.human_text! : c.ai_text
    const copyFrom = c.spec_basis.find((b) => /^청구항 \d+$/.test(b.location ?? ''))
    return (
      <div key={c.claim} style={box}>
        {head(
          claimKind(c.before, text),
          <>
            {edited && humanTag}
            {edited && (
              <Typography.Link onClick={() => toggleAi(key)}>{showAi ? '고친 글 보기' : 'AI 원문 보기'}</Typography.Link>
            )}
            {!isEditing && (
              <Button size="small" type="text" disabled={rebuilding} onClick={() => setEditing({ claim: c.claim, text: c.human_text ?? c.ai_text ?? '' })}>
                고치기
              </Button>
            )}
          </>,
        )}
        {note === 'written' && (
          <Alert type="warning" showIcon message="직접 쓴 방향으로 바뀜 · 이 초안은 이전 방향으로 만든 것이에요. AI는 이 묶음 초안을 다시 만들지 않으니 직접 대응해 주세요" />
        )}
        {note === 'changed' && (
          <Alert type="warning" showIcon message="선택이 바뀜 · 다시 만들어야 함. 이 초안은 이전 방향으로 만든 것이라 다시 확인이 필요해요" />
        )}
        {isEditing ? (
          editor
        ) : (
          <p className="body1" style={{ lineHeight: '28px', margin: 0 }}>
            {/* 바뀐 곳은 변경 추적으로: OA 당시 청구항 → 보여 주는 글 */}
            <TrackedText before={c.before} after={text} mode="amend" />
          </p>
        )}
        {edited && !showAi && !isEditing && (
          <div>
            <span className="label2 t3">AI 초안 → 고친 글 (검정 밑줄이 사람이 고친 곳)</span>
            <p className="body1" style={{ lineHeight: '28px', margin: 0 }}>
              <TrackedText before={c.ai_text} after={c.human_text!} mode="human" />
            </p>
          </div>
        )}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          <span className="label2 t3">
            {copyFrom ? `${copyFrom.location}에서 옮김 · ` : ''}근거
          </span>
          {c.spec_basis.length === 0 && <span className="label2 t3">찾지 못함</span>}
          {c.spec_basis.map((b) => {
            const where = b.location ?? (b.page !== null ? `${b.page}쪽` : b.document_id)
            return (
              <Button
                key={`${b.document_id}-${where}`}
                type="link"
                size="small"
                onClick={() => openCite({ title: `근거 ${where}`, items: [b], status: drafts.status, note: null })}
              >
                {where.startsWith('[') ? `최초 명세서 ${where}` : where}
              </Button>
            )
          })}
        </div>
        {respText && <span className="label2 t3">{respText}</span>}
      </div>
    )
  }

  // 번호 불일치가 가리킨 칸: 빨간 물결 밑줄 + 줄 아래 작은 글 (문장 위치는 데이터에 없다)
  const mismatchesOf = (title: string) => drafts.check.number_mismatches.filter((m) => m.where === title)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
      {/* 실행이 도는 동안 아래 초안은 이전 것: 새 초안으로 보이지 않게 한 줄 */}
      {rebuilding && (
        <Alert type="info" showIcon message="초안 다시 만드는 중 · 지금 보이는 초안은 이전 방향으로 만든 것이에요. 끝나면 새 초안으로 바뀌어요 · 그때까지는 옛 초안을 고칠 수 없어요" />
      )}
      <CoverageTable model={coverage} />
      <FixList
        fixes={fixes}
        caseItems={caseItems}
        hasCheck={caseCheck !== null}
        onShowClaims={() => setView('claims')}
        onShowOpinion={(title) => {
          setView('opinion')
          // 화면이 바뀐 뒤 그 칸으로 내린다 (칸 id = 제목)
          setTimeout(() => document.getElementById(`op-${title}`)?.scrollIntoView({ block: 'center' }), 0)
        }}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <Segmented
            size="large"
            value={view}
            onChange={setView}
            options={[
              { label: '의견서 초안', value: 'opinion' },
              { label: '보정 청구항 초안', value: 'claims' },
            ]}
          />
          <span style={{ flex: '1 1 auto' }} />
          <AiTag>{`AI 초안 · 묶음 선택 ${pickSource}`}</AiTag>
          {/* 내려받기는 API가 자리만이라 막아 둔다 */}
          <Tooltip title="서버가 오면 내려받을 수 있어요">
            <Button disabled>내려받기</Button>
          </Tooltip>
        </div>
        {view === 'opinion' ? (
          <>
            <span className="label2 t3">글을 눌러 바로 고칠 수 있어요. 고친 문장은 "직접 고침"으로 남고, AI 원문은 그대로 남아요.</span>
            {drafts.opinion.map((s, i) => {
              const key = `s:${s.key}`
              const mism = mismatchesOf(s.title)
              const isEditing = editing?.section === s.key
              const edited = s.human_text !== null
              const showAi = aiShown.includes(key)
              const startEdit = () => !rebuilding && setEditing({ section: s.key, text: s.human_text ?? s.ai_text })
              return (
                <div key={s.key} id={`op-${s.title}`} style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <h3 className="headline1" style={{ margin: 0 }}>{`${i + 1}. ${s.title}`}</h3>
                    {edited && humanTag}
                    {edited && (
                      <Typography.Link onClick={() => toggleAi(key)}>{showAi ? '고친 글 보기' : 'AI 원문 보기'}</Typography.Link>
                    )}
                  </div>
                  {isEditing ? (
                    editor
                  ) : (
                    <p
                      className="body1"
                      role="button"
                      tabIndex={0}
                      onClick={startEdit}
                      onKeyDown={(e) => e.key === 'Enter' && startEdit()}
                      style={{
                        lineHeight: '28px',
                        margin: 0,
                        cursor: 'text',
                        ...(mism.length > 0 ? { textDecoration: 'underline wavy var(--fg-negative-text)', textUnderlineOffset: 5 } : {}),
                      }}
                    >
                      {edited && !showAi ? (
                        <TrackedText
                          before={s.ai_text}
                          after={s.human_text!}
                          mode="human"
                          renderText={(t) => <LinkedText text={t} evidence={allEvidence} onOpen={openBasis} />}
                        />
                      ) : (
                        <LinkedText text={showAi || !edited ? s.ai_text : s.human_text!} evidence={allEvidence} onOpen={openBasis} />
                      )}
                    </p>
                  )}
                  {mism.map((m) => (
                    <span key={m.detail} className="label2" style={{ color: 'var(--fg-negative-text)' }}>
                      검사에 걸림 · {m.detail}
                    </span>
                  ))}
                </div>
              )
            })}
          </>
        ) : (
          <>
            <span className="label2 t3">검토용 초안이에요. 보정이 적법한지는 판단하지 않아요. AI가 바꾼 곳은 파랑, 지운 곳은 줄을 그었어요. 사람이 고친 곳은 검정 밑줄이에요.</span>
            {drafts.claims.map(claimView)}
          </>
        )}
      </div>
    </div>
  )
}
