import { Button, Steps } from 'antd'
import { useState } from 'react'
import { Link, Outlet, ScrollRestoration, useLocation, useNavigate, useRouteLoaderData } from 'react-router'
import { api } from '../api'
import { NumberInputForm } from '../components/NumberInputForm'
import { CaseInfo } from '../components/CaseInfo'
import { currentRunText, isPreviousResult } from '../previousResult'
import { HumanCheckTag } from '../components/Marks'
import { type OpenCite, type OpenEvidence, type OpenPage, SourceContext } from '../components/sourceContext'
import { type CitedState, type PanelEvidence, SourcePanel } from '../components/SourcePanel'
import { RunNotice } from '../components/RunNotice'
import { StatusTag } from '../components/StatusTag'
import { TodoRows } from '../components/TodoList'
import { noticeKindLabel, runStateLabel, waitingForLabel } from '../labels'
import type { OALoaderData } from '../loaders'
import { refreshRun, isRunEnded, isSelectionRunActive } from '../runPoll'
import { DIRECTIONS_UNKNOWN_NOTE, directTodos, todoCountText } from '../todos'
import { useRunSnapshot } from '../useRunSnapshot'
import type { LatestRun } from '../types/provisional/case'
import { differenceElements } from '../pages/compare/differences'

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
// 실행 줄이 아직 없으면(run null) 끝난 실행처럼 결과 유무만 보인다
// previous: 보이는 결과가 이전 실행 것이면 "끝남" 대신 "이전 결과" (서버는 실행이 끝나야 그 실행 결과를 연다)
// waitingFor: 사람 기다림의 이유 (GET /runs/{id}의 waiting_for). 출원번호·발송번호를 기다리면 정리 단계, 방향 고르기면 방향 단계에 둔다
function stepItems(
  run: LatestRun | null,
  ready: (boolean | null)[],
  todoText: string,
  previous: boolean,
  waitingFor: string | null,
  counts: (string | undefined)[],
  smallRun: boolean,
): StepItem[] {
  const doneText = previous ? '이전 결과' : '끝남'
  const ended = run === null || isRunEnded(run.state)
  const firstMissing = ready.indexOf(false) // 결과 없는 첫 단계 (모두 있으면 -1). null(모름)은 건너뛴다
  const stepText = run?.current_step ? (
    <div className="label2 t3">{run.current_step}</div>
  ) : undefined
  return STEPS.map((s, i) => {
    const base: StepItem = { title: s.label }
    // 결과 유무를 알 수 없었던 단계(확인 호출 실패)는 지어내지 않고 "모름"
    if (ready[i] === null) return { ...base, description: '모름', status: 'wait' }
    // 끝난 실행이 아니고 결과도 없는 단계는 눌러 가 봐야 빈 화면이라 막는다
    if (run === null || (ended && run.state !== 'failed' && run.state !== 'cancelled')) {
      if (run?.state === 'waiting_for_human') {
        // 사람 기다림: 출원번호·발송번호 확인이면 정리 단계, 그 밖에는 정리 결과가 없으면 정리 단계·있으면 방향 단계가 기다리는 자리
        const numberWait = waitingFor === 'application_number' || waitingFor === 'dispatch_number'
        const waitAt = numberWait || !ready[0] ? 0 : 2
        if (i === waitAt) return { ...base, description: waitingForLabel(waitingFor), status: 'process' }
      }
      // 끝난 실행: 정리는 직접 할 일, 대비·방향은 결과에서 센 개수 (초안 "고칠 곳"은 서버 초안에 검사 결과가 없어 비움)
      if (!ready[i]) return base
      return { ...base, description: i === 0 ? `직접 할 일 ${todoText}` : counts[i] }
    }
    if (run.state === 'failed' || run.state === 'cancelled') {
      if (ready[i]) return { ...base, description: i === 0 ? `직접 할 일 ${todoText}` : doneText }
      if (i === firstMissing)
        return run.state === 'failed'
          ? { ...base, description: <><div>멈춤</div>{stepText}</>, status: 'error', disabled: true }
          : { ...base, description: '취소됨', status: 'wait', disabled: true }
      return { ...base, status: 'wait', disabled: true }
    }
    // queued · running
    // 고르기로 시작한 작은 실행(smallRun)은 초안만 다시 만드니 4단계(초안)만 "다시 만드는 중"으로 보인다.
    // latest_run에는 실행 종류가 없어서, 그 밖의 실행(전체 다시 돌리기 등)은 4단계도 다른 단계처럼 doneText·finish로 두고
    // 지금 도는 단계 이름(stepText)을 초안 단계에 붙이지 않는다
    if (ready[i] && i === 3 && smallRun) return { ...base, description: <>{run.current_step ? stepText : <div>다시 만드는 중</div>}</>, status: 'process' }
    if (ready[i]) return { ...base, description: doneText, status: 'finish' }
    if (i === firstMissing) return { ...base, description: <><div>찾는 중</div>{stepText}</>, status: 'process', disabled: true }
    return { ...base, description: '대기', status: 'wait', disabled: true }
  })
}

// 단계 막대 설명의 개수 (디자인 B): 대비 "차이점 후보 N" = 대비표마다 차이점 후보 구성요소 수의 합,
// 방향 "고를 것 N" = 직접 판단이 필요한데 아직 안 고른 묶음 (직접 할 일의 방향 고르기와 같은 셈).
// 결과를 모르거나 목록이 비면(넘김·보류로 빈 목록 + 빈 이유) 비운다: "0"으로 보이면 셀 결과가 있는 것처럼 읽힌다
function stepCounts(d: OALoaderData): (string | undefined)[] {
  const tables = d.comparisons?.length ? d.comparisons : null
  const dirs = d.directions?.length ? d.directions : null
  // 구성요소 기준으로 센다 (진보성은 인용발명 칸마다가 아니라 어느 인용발명에서도 못 찾은 구성요소만)
  const diffs = tables?.reduce((n, t) => n + differenceElements(t).length, 0)
  const toPick = dirs?.filter((x) => x.flags.includes('needs_human_judgment') && x.selection === null).length
  return [undefined, diffs === undefined ? undefined : `차이점 후보 ${diffs}`, toPick === undefined ? undefined : `고를 것 ${toPick}`, undefined]
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
  // 판에 연 인용문헌의 원문 전체 (대비 줄을 누를 때 받는다). loading/실패도 판에 그대로 보인다
  const [cited, setCited] = useState<CitedState | null>(null)
  // 오른쪽 판 탭: 'oa'(의견제출통지서) 또는 인용문헌 번호. 링크를 누르면 저절로 바뀐다
  const [tab, setTab] = useState<string>('oa')
  const [infoOpen, setInfoOpen] = useState(false)
  const [todoOpen, setTodoOpen] = useState(false)

  const r = data.oaResult?.result ?? null
  const todos = directTodos(data)
  const todoText = todoCountText(todos)
  // 실행 상태는 폴링 값 (loader가 준 값에서 시작해 2.5초마다 GET /runs/{id}만 부른다)
  const snap = useRunSnapshot(data.oa.latest_run)
  const run = snap?.run ?? null
  const smallRun = isSelectionRunActive(snap) // 고르기로 시작한 작은 실행이 도는 중: 초안만 다시 만든다
  const previous = isPreviousResult(data.oaResult, data.oa.latest_run, snap)
  const runError = snap?.error ?? null
  const ready: (boolean | null)[] = [data.ready.summary, data.ready.compare, data.ready.directions, data.ready.drafts]
  const reviewCount = data.reviewItems?.length ?? null

  // 아무것도 안 골랐으면 통지서 첫 거절이유가 있는 쪽을 기본으로 (없으면 1쪽)
  const defaultPage = r?.rejections.map((x) => x.article.page).find((p) => p !== null) ?? 1
  const shown = source ?? { page: defaultPage, text: null }

  // 쪽 링크를 누르면 판을 펴고 그 쪽으로. 쪽을 모르면(null) 판만 편다
  const scrollToPanel = (page: number | null = null) =>
    // 판 안에서는 강조 줄 → 그 쪽 머리 → 판 순서로 찾아 내린다. 원문은 전체 쪽을 한 판에 이어 보이므로
    // 강조가 없으면 그 쪽 머리로 간다 (effect 없이 그린 뒤 한 번)
    requestAnimationFrame(() => {
      const hl = document.getElementById('source-highlight')
      const pageHead = page !== null ? document.getElementById(`source-page-${page}`) : null
      ;(hl ?? pageHead ?? document.getElementById('source-panel'))?.scrollIntoView({
        block: hl ? 'center' : 'start',
      })
    })
  const openPage: OpenPage = (page, text, scroll = true) => {
    if (page !== null) setSource({ page, text })
    setEvidenceAt(null)
    setTab('oa')
    // scroll=false("자세히"로 줄을 펼칠 때)는 판을 새로 펴지 않는다: 열려 있을 때만 문서를 바꾸고 접힘은 그대로.
    // 쪽 링크·근거 링크를 직접 누를 때(scroll=true)만 편다
    if (scroll) {
      setSrcOpen(true)
      scrollToPanel(page)
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
    // 어느 탭에서 열지: 인용문헌 번호가 없으면 근거의 문서로 정한다
    // (명세서 문단 근거 → '명세서' 탭, 인용문헌 → 그 문헌 탭, 둘 다 아니면 탭 없이 근거 글만)
    const doc = ref.docId ?? ref.items[0]?.document_id ?? null
    const target = doc !== null && doc === specDocumentId ? 'spec' : doc !== null && citeTabs.some((t) => t.key === doc) ? doc : null
    setEvidenceAt({ data: { kind: 'cite', ref: { ...ref, docId: target ?? ref.docId ?? null } }, owner })
    setSrcOpen(true)
    scrollToPanel()
    if (target) {
      setTab(target)
      if (target !== 'spec') loadCited(target, true)
    }
  }
  // 인용문헌 원문 전체(글자 보기용)를 받는다. 같은 문헌이면 다시 받지 않는다 (effect 없이 누른 그 자리에서)
  const loadCited = (docId: string, scroll: boolean) => {
    if (cited?.docId === docId && cited.doc) {
      if (scroll) scrollToCited()
      return
    }
    setCited({ docId, doc: null, failed: false })
    api
      .getCitedDocument(docId)
      .then((doc) => {
        setCited({ docId, doc, failed: false })
        if (scroll) scrollToCited()
      })
      .catch(() => setCited({ docId, doc: null, failed: true }))
  }
  // 탭을 직접 누르면 그 문서로 (법률 근거를 보던 중이면 닫는다)
  const selectTab = (key: string) => {
    if (evidence?.kind === 'legal') setEvidenceAt(null)
    setTab(key)
    if (key !== 'oa' && key !== 'spec') loadCited(key, false)
  }
  // 탭 목록: 의견제출통지서 + 이 통지서가 인용한 문헌 (번호가 있는 것만, 처음 나온 라벨로)
  const citeTabs = (() => {
    const seen = new Map<string, string>()
    for (const rej of r?.rejections ?? [])
      for (const c of rej.citations) {
        const no = c.number.value ?? c.number.raw_text
        if (no && !seen.has(no)) seen.set(no, c.label)
      }
    return [...seen].map(([no, label]) => ({ key: no, label: `${label} ${no}` }))
  })()
  // 이 출원의 명세서(출원서) 문서: 있으면 '명세서' 탭을 둔다
  const specDocumentId = data.specDocumentId
  // 강조한 근거 문단(없으면 판)으로 판 안에서 내린다
  const scrollToCited = () =>
    requestAnimationFrame(() =>
      (document.getElementById('cited-highlight') ?? document.getElementById('source-panel'))?.scrollIntoView({ block: 'center' }),
    )

  return (
    <SourceContext value={{ openPage, openEvidence, openCite }}>
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
                : `정리 결과 없음 · ${run ? runStateLabel[run.state] : '아직 정리를 시작하지 않았습니다'}`}
            </span>
            {/* 지금 보이는 결과가 이전 실행 것이면 머리에서도 짧게 (정리 단계 머리에 자세히) */}
            {previous && run && (
              <span className="label2" style={{ color: 'var(--fg-cautionary-text)' }}>
                이전 실행 결과 · {currentRunText(run)}
              </span>
            )}
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
          {/* 출원번호 입력을 기다리면 사건 머리에 입력 칸 (F5 design 6절) */}
          {run?.state === 'waiting_for_human' && snap?.waitingFor === 'application_number' && (
            <NumberInputForm kind="application_number" targetId={data.oa.case_id} runId={run.run_id} read={r?.application_number ?? null} />
          )}
          {/* 발송번호 입력을 기다리면 같은 자리에 발송번호 입력 칸 */}
          {run?.state === 'waiting_for_human' && snap?.waitingFor === 'dispatch_number' && (
            <NumberInputForm kind="dispatch_number" targetId={data.oa.oa_id} runId={run.run_id} read={r?.dispatch_number ?? null} />
          )}
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
              items={stepItems(run, ready, todoText, previous, snap?.waitingFor ?? null, stepCounts(data), smallRun)}
            />
            {/* 실행이 도는 동안: 상태를 못 받았으면 알리고, 직접 새로 받는 버튼 */}
            {/* 실패·취소는 단계 결과가 다 있어도 보여야 한다 */}
            <div style={{ marginTop: 8 }}>
              {snap && <RunNotice oaId={data.oa.oa_id} snap={snap} />}
            </div>
            {data.warnings.map((w) => (
              <div key={w} className="label2" style={{ marginTop: 8, color: 'var(--fg-cautionary-text)' }}>
                {w}
              </div>
            ))}
            {/* 사람 기다림은 폴링이 멈춘 상태지만 방향을 고른 뒤 다시 받아야 해서 버튼은 둔다 */}
            {run !== null && (!isRunEnded(run.state) || run.state === 'waiting_for_human' || runError !== null) && (
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
              <>
                <TodoRows todos={todos.todos} variant="panel" />
                {!todos.directionsKnown && <span className="label1 t3">{DIRECTIONS_UNKNOWN_NOTE}</span>}
              </>
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
              // 원문 판을 접으면 본문이 남은 폭을 다 쓴다 (펴 있을 때만 읽기 좋은 폭으로 묶음)
              maxWidth: srcOpen ? 920 : 'none',
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
            cited={cited}
            tabs={[
              { key: 'oa', label: '의견제출통지서' },
              ...(specDocumentId ? [{ key: 'spec', label: '명세서' }] : []),
              ...citeTabs,
            ]}
            tab={tab}
            onTab={selectTab}
            applicationNumber={r?.application_number.value ?? null}
            specDocumentId={specDocumentId}
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
