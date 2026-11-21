import { Alert, App, Button, Input, Segmented, Space, Tag, Tooltip, Typography } from 'antd'
import { useContext, useState } from 'react'
import { Link, useLoaderData, useRouteLoaderData } from 'react-router'
import { api, API_MODE } from '../../api'
import { SourceContext } from '../../components/sourceContext'
import { TrackedText } from '../../components/TrackedText'
import type { DraftsLoaderData, OALoaderData } from '../../loaders'
import { LOW_CONFIDENCE_TEXT, rejectionKindLabel } from '../../labels'
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
type BasisNote = 'changed' | 'picked' | null

const humanTag = (
  <Tag bordered={false} style={{ marginInlineEnd: 0 }}>
    직접 고침
  </Tag>
)

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
  const { drafts: initial, directions, caseCheck } = useLoaderData() as DraftsLoaderData
  const { oaResult } = useRouteLoaderData('oa') as OALoaderData
  const { message } = App.useApp()
  const { openCite } = useContext(SourceContext)
  const [drafts, setDrafts] = useState<DraftsWithCheck | null>(initial)
  const [view, setView] = useState<'opinion' | 'claims'>('opinion')
  const [aiShown, setAiShown] = useState<string[]>([]) // AI 원문을 펼친 칸: 's:<key>' / 'c:<청구항>'
  const [editing, setEditing] = useState<Editing>(null)

  if (drafts === null) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <h2 className="heading2">대응 현황 · 거절이유 × 청구항</h2>
        <span className="body1 t2">초안이 아직 없어 대응 현황을 셀 수 없어요</span>
        {API_MODE === 'mock' && <span className="label2 t3">예시 초안은 '가상의 영상 처리 장치' 사건에만 있어요</span>}
      </div>
    )
  }

  const rejections = oaResult?.result.rejections ?? []
  // AI가 다루지 않은 거절이유: 사건 전체 검사 + 정리 결과의 supported=false
  const unsupported = [...new Set([...(caseCheck?.unsupported_rejections ?? []), ...rejections.filter((r) => !r.supported).map((r) => r.no)])].sort(
    (a, b) => a - b,
  )
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
    const now = directions.find((d) => d.unit_id === unitId)?.selection?.candidate_id ?? null
    const basis = drafts.based_on.find((b) => b.unit_id === unitId)?.candidate_id ?? null
    if (basis === null) return now === null ? null : 'picked'
    return now !== basis ? 'changed' : null
  }
  // 묶음 선택 출처: 고른 묶음 중 사람이 고른 것이 있나
  const picked = directions.flatMap((d) => (d.selection ? [d.selection] : []))
  const humanPicked = picked.filter((s) => s.origin === 'human_selected' || s.origin === 'human_edited').length
  const pickSource = humanPicked === 0 ? 'AI 기본값' : humanPicked === picked.length ? '직접 고름' : '일부 직접 고름'

  // 근거 링크는 의견서·보정 청구항 근거 목록에서 같은 위치를 찾아 원문 판으로
  const allEvidence = [...drafts.evidence, ...drafts.claims.flatMap((c) => c.spec_basis)]
  const openEvidence = (token: string, e: Evidence1) =>
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
          {note === 'picked' ? (
            <Alert
              type="info"
              showIcon
              message="방향을 골랐어요. 이 묶음의 초안은 실행을 다시 돌리면 만들어져요 · 다시 만들어야 함"
              description={API_MODE === 'mock' ? 'mock 예시 초안은 바뀌지 않아요' : undefined}
            />
          ) : (
            <Space wrap>
              <span className="body1" style={{ fontWeight: 600 }}>직접 판단 필요: 방향을 골라 주세요</span>
              <Link to="../directions" relative="path">
                <Button size="small">고르기</Button>
              </Link>
            </Space>
          )}
          {c.held_reason && <span className="label2 t3">{c.held_reason}</span>}
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
              <Button size="small" type="text" onClick={() => setEditing({ claim: c.claim, text: c.human_text ?? c.ai_text ?? '' })}>
                고치기
              </Button>
            )}
          </>,
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
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
          <Tag color="purple" bordered={false} style={{ marginInlineEnd: 0 }}>{`AI 초안 · 묶음 선택 ${pickSource}`}</Tag>
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
              const startEdit = () => setEditing({ section: s.key, text: s.human_text ?? s.ai_text })
              return (
                <div key={s.key} id={`op-${s.title}`} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
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
                        ...(mism.length > 0 ? { textDecoration: 'underline wavy var(--fg-negative-primary)', textUnderlineOffset: 5 } : {}),
                      }}
                    >
                      {edited && !showAi ? (
                        <TrackedText
                          before={s.ai_text}
                          after={s.human_text!}
                          mode="human"
                          renderText={(t) => <LinkedText text={t} evidence={allEvidence} onOpen={openEvidence} />}
                        />
                      ) : (
                        <LinkedText text={showAi || !edited ? s.ai_text : s.human_text!} evidence={allEvidence} onOpen={openEvidence} />
                      )}
                    </p>
                  )}
                  {mism.map((m) => (
                    <span key={m.detail} className="label2" style={{ color: 'var(--fg-negative-primary)' }}>
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
