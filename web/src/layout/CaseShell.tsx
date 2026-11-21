import { Button, Steps } from 'antd'
import { useState } from 'react'
import { Link, Outlet, ScrollRestoration, useLocation, useNavigate, useRouteLoaderData } from 'react-router'
import { CaseInfo } from '../components/CaseInfo'
import { HumanCheckTag } from '../components/Marks'
import { type OpenCite, type OpenEvidence, type OpenSource, SourceContext } from '../components/sourceContext'
import { type PanelEvidence, SourcePanel } from '../components/SourcePanel'
import { StatusTag } from '../components/StatusTag'
import { TodoRows } from '../components/TodoList'
import { noticeKindLabel, runStateLabel } from '../labels'
import type { OALoaderData } from '../loaders'
import { refreshRun, isRunEnded } from '../runPoll'
import { directTodos } from '../todos'
import { useRunSnapshot } from '../useRunSnapshot'
import type { LatestRun } from '../types/provisional/case'

// 사건 안의 단계 4개 (디자인 B 고친 판). 단계마다 주소가 있어 새로고침·뒤로 가기가 된다
const STEPS = [
  { key: 'summary', label: '정리', path: '' },
  { key: 'compare', label: '인용발명 대비', path: '/compare' },
  { key: 'directions', label: '대응 방향', path: '/directions' },
  { key: 'drafts', label: '초안', path: '/drafts' },
]

type StepItem = { title: string; description?: React.ReactNode; status?: 'wait' | 'process' | 'finish' | 'error'; disabled?: boolean }

// 단계 막대 항목 (D5). 단계 상태는 "결과가 있나"(로더가 받은 값)로 정한다. current_step은 자유 글이라 파싱하지 않고 그대로 보인다.
// 실행 중: 결과 있는 단계 "끝남", 결과 없는 첫 단계 "찾는 중", 그 뒤 "대기". 실행이 끝났으면 지금까지처럼 (정리에 직접 할 일 N)
function stepItems(run: LatestRun, ready: boolean[], todoText: string): StepItem[] {
  const ended = isRunEnded(run.state)
  const firstMissing = ready.indexOf(false) // 결과 없는 첫 단계 (모두 있으면 -1)
  const stepText = run.current_step ? (
    <div className="label2 t3">{run.current_step}</div>
  ) : undefined
  return STEPS.map((s, i) => {
    const base: StepItem = { title: s.label }
    // 끝난 실행이 아니고 결과도 없는 단계는 눌러 가 봐야 빈 화면이라 막는다
    if (ended && run.state !== 'failed' && run.state !== 'cancelled') {
      if (run.state === 'waiting_for_human') {
        // 사람 기다림: 정리 결과가 없으면 정리 단계, 있으면 방향 단계가 기다리는 자리
        const waitAt = ready[0] ? 2 : 0
        if (i === waitAt) return { ...base, description: '고르기 기다림', status: 'process' }
      }
      return { ...base, description: i === 0 && ready[0] ? `직접 할 일 ${todoText}` : undefined }
    }
    if (run.state === 'failed' || run.state === 'cancelled') {
      if (ready[i]) return { ...base, description: i === 0 ? `직접 할 일 ${todoText}` : '끝남' }
      if (i === firstMissing)
        return run.state === 'failed'
          ? { ...base, description: <><div>멈춤</div>{stepText}</>, status: 'error', disabled: true }
          : { ...base, description: '취소됨', status: 'wait', disabled: true }
      return { ...base, status: 'wait', disabled: true }
    }
    // queued · running
    if (ready[i]) return { ...base, description: '끝남', status: 'finish' }
    if (i === firstMissing) return { ...base, description: <><div>찾는 중</div>{stepText}</>, status: 'process', disabled: true }
    return { ...base, description: '대기', status: 'wait', disabled: true }
  })
}

// 사건 틀: 머리(이름·통지 종류·제출기일·사건 정보) → 단계 막대 + 직접 할 일·원문 버튼 → 본문(왼쪽) + 참고 원문 판(오른쪽).
// 원문 판 상태와 "지금 연 원문"을 여기서 들고 있어서 단계를 옮겨도 접힘·쪽이 유지된다.
// 좁은 화면(<900px)에서는 flex-wrap으로 원문 판이 본문 아래로 내려간다
export function CaseShell() {
  const data = useRouteLoaderData('oa') as OALoaderData
  const navigate = useNavigate()
  const location = useLocation()
  const base = `/oas/${data.oa.oa_id}`
  const sub = location.pathname.slice(base.length).replace(/\/$/, '')
  const stepIdx = Math.max(
    0,
    STEPS.findIndex((s) => s.path === sub),
  )

  const [srcOpen, setSrcOpen] = useState(true)
  const [source, setSource] = useState<{ page: number; text: string | null } | null>(null)
  // 판에 연 법률 근거. 있으면 통지서 쪽 대신 근거 글을 보인다 (둘 중 하나만 열린다)
  // 연 자리(owner: 단계 주소 + 고른 묶음)를 같이 들고, 자리가 바뀌면 판은 그 단계 기본(통지서 쪽)으로 보인다
  const [evidenceAt, setEvidenceAt] = useState<{ data: PanelEvidence; owner: string } | null>(null)
  const owner = `${sub}|${new URLSearchParams(location.search).get('unit') ?? ''}`
  const evidence = evidenceAt && evidenceAt.owner === owner ? evidenceAt.data : null
  const [infoOpen, setInfoOpen] = useState(false)
  const [todoOpen, setTodoOpen] = useState(false)

  const r = data.oaResult?.result ?? null
  const todos = directTodos(data)
  const todoText = todos === null ? '모름' : String(todos.length)
  // 실행 상태는 폴링 값 (loader가 준 값에서 시작해 2.5초마다 GET /runs/{id}만 부른다)
  const { run, error: runError } = useRunSnapshot(data.oa.latest_run)
  const ready = [data.ready.summary, data.ready.compare, data.ready.directions, data.ready.drafts]
  const reviewCount = data.reviewItems?.length ?? data.materials?.review_items_count ?? null

  // 아무것도 안 골랐으면 통지서 첫 거절이유가 있는 쪽을 기본으로 (없으면 1쪽)
  const defaultPage = r?.rejections.map((x) => x.article.page).find((p) => p !== null) ?? 1
  const shown = source ?? { page: defaultPage, text: null }

  // 쪽 링크를 누르면 판을 펴고 그 쪽으로. 쪽을 모르면(null) 판만 편다
  const scrollToPanel = () =>
    // 판 안에서는 강조 줄(없으면 판)로, 좁은 화면에서 판이 본문 아래면 화면도 거기로 (effect 없이 그린 뒤 한 번)
    requestAnimationFrame(() =>
      (document.getElementById('source-highlight') ?? document.getElementById('source-panel'))?.scrollIntoView({
        block: 'nearest',
      }),
    )
  const openSource: OpenSource = (page, text, scroll = true) => {
    if (page !== null) setSource({ page, text })
    setEvidenceAt(null)
    // scroll=false("자세히"로 줄을 펼칠 때)는 판을 새로 펴지 않는다: 열려 있을 때만 문서를 바꾸고 접힘은 그대로.
    // 쪽 링크·근거 링크를 직접 누를 때(scroll=true)만 편다
    if (scroll) {
      setSrcOpen(true)
      scrollToPanel()
    }
  }
  // 법률 근거 열기: 근거 글(raw_text)을 판에 보인다
  const openEvidence: OpenEvidence = (src, checkedOn) => {
    setEvidenceAt({ data: { kind: 'legal', source: src, checkedOn }, owner })
    setSrcOpen(true)
    scrollToPanel()
  }

  // 대비 줄·후보 근거 열기: 공통 근거 위치를 판에 보인다
  const openCite: OpenCite = (ref) => {
    setEvidenceAt({ data: { kind: 'cite', ref }, owner })
    setSrcOpen(true)
    scrollToPanel()
  }

  return (
    <SourceContext value={{ openPage: openSource, openEvidence, openCite }}>
      {/* 자리 이동(#materials 등)을 단계가 바뀐 뒤에도 해 준다 */}
      <ScrollRestoration />
      <div style={{ display: 'flex', flexDirection: 'column', flex: '1 1 auto' }}>
        <div style={{ padding: '24px 32px 0', display: 'flex', flexDirection: 'column', gap: 6 }}>
          <Link to="/cases" className="label2 t3">
            사건 목록
          </Link>
          <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
            <h1 className="heading1">{data.oa.case_name}</h1>
            {/* 제출기일은 통지서에서 읽은 글자만. 남은 날 계산은 하지 않는다 */}
            <span className="body2 t3">
              {r
                ? `${r.notice_kind.value ? noticeKindLabel[r.notice_kind.value] : (r.notice_kind.raw_text ?? '통지 종류 모름')} · 제출기일 ${r.response_due.raw_text ?? '모름'}`
                : `정리 결과 없음 · ${runStateLabel[run.state]}`}
            </span>
            {r && <HumanCheckTag />}
            {r && r.response_due.status.value !== 'confirmed' && <StatusTag status={r.response_due.status} />}
            {r && r.status.value !== 'confirmed' && <StatusTag status={r.status} />}
            {r && (
              <Button type="text" size="small" onClick={() => setInfoOpen(!infoOpen)}>
                {infoOpen ? '사건 정보 접기' : '사건 정보'}
              </Button>
            )}
          </div>
          {r && infoOpen && <CaseInfo r={r} />}
        </div>

        <div
          style={{
            display: 'flex',
            gap: 24,
            padding: '20px 32px 16px',
            alignItems: 'center',
            flexWrap: 'wrap',
            borderBottom: '1px solid var(--line-neutral-tertiary)',
          }}
        >
          <div style={{ flex: '1 1 560px', minWidth: 0, maxWidth: 760 }}>
            <Steps
              size="small"
              current={stepIdx}
              onChange={(i) => navigate(base + STEPS[i].path)}
              items={stepItems(run, ready, todoText)}
            />
            {/* 실행이 도는 동안: 상태를 못 받았으면 알리고, 직접 새로 받는 버튼 */}
            {(!isRunEnded(run.state) || runError !== null) && (
              <div className="label2 t3" style={{ marginTop: 8 }}>
                {runError !== null && <span>상태를 받지 못했어요 · </span>}
                <Button type="link" size="small" onClick={() => void refreshRun(run.run_id)}>
                  새로 보기
                </Button>
              </div>
            )}
          </div>
          <span style={{ flex: '1 1 auto' }} />
          <Button type={todoOpen ? 'primary' : 'default'} onClick={() => setTodoOpen(!todoOpen)}>
            직접 할 일 {todoText}
          </Button>
          <Button onClick={() => setSrcOpen(!srcOpen)}>{srcOpen ? '원문 접기' : '원문 펴기'}</Button>
        </div>

        {todoOpen && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              padding: '4px 32px 8px',
              background: 'var(--bg-neutral-secondary)',
              borderBottom: '1px solid var(--line-neutral-tertiary)',
            }}
          >
            {todos === null ? (
              <span className="label1 t3" style={{ padding: '10px 0' }}>
                검토할 사항 목록을 받지 못해 직접 할 일 개수를 알 수 없어요. 제출기일은 통지서에서 직접 확인해 주세요.
              </span>
            ) : (
              <TodoRows todos={todos} variant="panel" />
            )}
            {/* 직접 할 일과 검토할 사항은 다른 숫자다: 전체 목록은 정리 단계 아래쪽 */}
            <div style={{ padding: '10px 0' }}>
              <Button type="link" size="small" onClick={() => navigate({ pathname: base, hash: '#review-items' })}>
                {reviewCount === null ? '검토할 사항 전체 보기' : `검토할 사항 ${reviewCount}건 전체 보기`}
              </Button>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', flexWrap: 'wrap', flex: '1 1 auto' }}>
          <section
            style={{
              flex: '999 1 560px',
              minWidth: 0,
              maxWidth: 920,
              padding: '32px 40px 80px',
              display: 'flex',
              flexDirection: 'column',
              gap: 40,
            }}
          >
            <Outlet />
          </section>
          <SourcePanel
            open={srcOpen}
            page={shown.page}
            highlight={shown.text}
            document={data.document}
            evidence={evidence}
            onToggle={() => setSrcOpen(!srcOpen)}
          />
        </div>
      </div>
    </SourceContext>
  )
}
