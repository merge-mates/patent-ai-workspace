import { Button, Steps } from 'antd'
import { useState } from 'react'
import { Link, Outlet, ScrollRestoration, useLocation, useNavigate, useRouteLoaderData } from 'react-router'
import { CaseInfo } from '../components/CaseInfo'
import { SourceContext } from '../components/sourceContext'
import { SourcePanel } from '../components/SourcePanel'
import { StatusTag } from '../components/StatusTag'
import { TodoRows } from '../components/TodoList'
import { noticeKindLabel, runStateLabel } from '../labels'
import type { OALoaderData } from '../loaders'
import { directTodos } from '../todos'

// 사건 안의 단계 4개 (디자인 B 고친 판). 단계마다 주소가 있어 새로고침·뒤로 가기가 된다
const STEPS = [
  { key: 'summary', label: '정리', path: '' },
  { key: 'compare', label: '인용발명 대비', path: '/compare' },
  { key: 'directions', label: '대응 방향', path: '/directions' },
  { key: 'drafts', label: '초안', path: '/drafts' },
]

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
  const [infoOpen, setInfoOpen] = useState(false)
  const [todoOpen, setTodoOpen] = useState(false)

  const r = data.oaResult?.result ?? null
  const todos = directTodos(data)
  const todoText = todos === null ? '모름' : String(todos.length)
  const reviewCount = data.reviewItems?.length ?? data.materials?.review_items_count ?? null

  // 아무것도 안 골랐으면 통지서 첫 거절이유가 있는 쪽을 기본으로 (없으면 1쪽)
  const defaultPage = r?.rejections.map((x) => x.article.page).find((p) => p !== null) ?? 1
  const shown = source ?? { page: defaultPage, text: null }

  // 쪽 링크를 누르면 판을 펴고 그 쪽으로. 쪽을 모르면(null) 판만 편다
  const openSource = (page: number | null, text: string | null) => {
    if (page !== null) setSource({ page, text })
    setSrcOpen(true)
  }

  return (
    <SourceContext value={openSource}>
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
                ? `${r.notice_kind.value ? noticeKindLabel[r.notice_kind.value] : (r.notice_kind.raw_text ?? '통지 종류 모름')} · 제출기일 ${r.response_due.raw_text ?? '직접 확인'}`
                : `정리 결과 없음 · ${runStateLabel[data.oa.latest_run.state]}`}
            </span>
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
              items={STEPS.map((s) => ({
                title: s.label,
                // 진행 상태 표시는 다음 조각. 지금은 정리 단계에 직접 할 일 개수만
                description: s.key === 'summary' ? `직접 할 일 ${todoText}` : undefined,
              }))}
            />
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
            onToggle={() => setSrcOpen(!srcOpen)}
          />
        </div>
      </div>
    </SourceContext>
  )
}
