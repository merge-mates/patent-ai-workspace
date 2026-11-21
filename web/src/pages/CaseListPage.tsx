import { Button, Table } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link, useLoaderData, useNavigate } from 'react-router'
import { HumanCheckTag } from '../components/Marks'
import { StatusTag } from '../components/StatusTag'
import { rejectionKindLabel } from '../labels'
import type { CasesLoaderData } from '../loaders'
import type { CaseListExtra, CaseStage } from '../types/provisional/caseListExtra'
import type { CaseSummary } from '../types/provisional/case'

// 지금 단계 글자 (사건 작업 틀의 단계 이름과 같게)
const stageLabel: Record<CaseStage, string> = {
  summary: '정리',
  compare: '인용발명 대비',
  directions: '대응 방향',
  drafts: '초안',
}

// 표 한 줄: 사건 + 그 사건의 추가 값 (모르면 null)
interface Row {
  c: CaseSummary
  extra: CaseListExtra | null
}

// 최후거절이유통지는 보정 방식이 제한된다 (특허법 제47조제3항, docs/product/domain/보정_범위.md)
const FINAL_NOTE = '최후거절이유통지 · 보정은 범위 줄이기·오기 정정·명확화·이전 보정 되돌리기만'

const columns: ColumnsType<Row> = [
  {
    title: '제출기일',
    width: 140,
    // 통지서에서 읽은 글자 그대로. 남은 날 계산은 하지 않는다
    render: (_, { extra }) =>
      extra?.response_due_raw ? (
        <span style={{ fontWeight: 600 }}>
          {extra.response_due_raw} <HumanCheckTag />
        </span>
      ) : (
        '모름'
      ),
  },
  {
    title: '사건',
    render: (_, { c }) => (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Link to={`/oas/${c.latest_oa.oa_id}`} style={{ color: 'var(--fg-neutral-primary)', fontWeight: 600 }}>
            {c.case_name}
          </Link>
          {/* 확인됨은 꼬리표 없음. 확인되지 않음·충돌은 숨기지 않는다 */}
          {c.status !== 'confirmed' && <StatusTag status={c.status} detail={false} />}
        </span>
        {c.latest_oa.notice_kind === 'final' && (
          <span style={{ fontSize: 13, lineHeight: '18px', color: 'var(--fg-cautionary-text)' }}>{FINAL_NOTE}</span>
        )}
      </div>
    ),
  },
  {
    title: '거절이유',
    width: 200,
    // 최근 OA의 거절이유 종류. 비면 "없음"
    render: (_, { c }) =>
      c.rejection_kinds.length > 0 ? c.rejection_kinds.map((k) => rejectionKindLabel[k]).join(' · ') : '없음',
  },
  {
    title: '지금 단계',
    width: 160,
    // 실행이 실패한 사건은 단계보다 먼저 알린다
    render: (_, { c, extra }) =>
      c.run_state === 'failed' ? (
        <span style={{ color: 'var(--fg-negative-text)', fontWeight: 600 }}>실패</span>
      ) : extra?.stage ? (
        stageLabel[extra.stage]
      ) : (
        '모름'
      ),
  },
  {
    title: '직접 할 일',
    width: 120,
    align: 'right',
    // 0개면 "없음", 모르면 "모름" (서로 다르다)
    render: (_, { extra }) =>
      extra?.todo_count == null ? '모름' : extra.todo_count > 0 ? `${extra.todo_count}개` : '없음',
  },
]

// 사건 목록 (디자인 B 고친 판 PMain): 오늘 먼저 볼 사건 한 덩어리 + 모든 사건 표. 카드 상자 없이 줄
export function CaseListPage() {
  const { cases, extras, focus } = useLoaderData() as CasesLoaderData
  const navigate = useNavigate()
  const rows: Row[] = cases.map((c) => ({ c, extra: extras[c.case_id] ?? null }))
  const anyUnknown = rows.some((r) => r.extra?.todo_count == null)
  const focusExtra = focus ? extras[focus.case.case_id] : undefined

  return (
    <main
      style={{ maxWidth: 1120, margin: '0 auto', padding: '40px 32px 80px', display: 'flex', flexDirection: 'column', gap: 40 }}
    >
      <section style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <span className="label1 t3">오늘 먼저 볼 사건</span>
        {focus ? (
          <div
            style={{
              display: 'flex',
              gap: 24,
              alignItems: 'center',
              flexWrap: 'wrap',
              paddingBottom: 24,
              borderBottom: '1px solid var(--line-neutral-tertiary)',
            }}
          >
            <div style={{ flex: '1 1 420px', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <Link
                to={`/oas/${focus.case.latest_oa.oa_id}`}
                className="heading1"
                style={{ color: 'var(--fg-neutral-primary)' }}
              >
                {focus.case.case_name}
              </Link>
              <span className="body2 t2">
                제출기일 {focusExtra?.response_due_raw ?? '모름'} <HumanCheckTag /> · 직접 할 일 {focusExtra?.todo_count}개:{' '}
                {focus.titles.join(', ')}
                {(focusExtra?.todo_count ?? 0) > focus.titles.length ? ' …' : ''}
              </span>
            </div>
            <Button size="large" onClick={() => navigate(`/oas/${focus.case.latest_oa.oa_id}`)}>
              이어서 보기
            </Button>
          </div>
        ) : (
          <p className="body2 t2" style={{ margin: 0 }}>
            {anyUnknown
              ? '직접 할 일을 아직 알 수 없는 사건이 있어 고르지 못했어요. 아래 표에서 사건을 열어 주세요.'
              : '직접 할 일이 남은 사건이 없어요.'}
          </p>
        )}
      </section>

      <section style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <h2 className="heading2" style={{ margin: 0 }}>
          모든 사건
        </h2>
        <div style={{ overflowX: 'auto' }}>
          <Table<Row>
            rowKey={(r) => r.c.case_id}
            size="middle"
            columns={columns}
            dataSource={rows}
            pagination={false}
            scroll={{ x: 720 }}
            locale={{ emptyText: '아직 사건이 없습니다. 위 "통지서 올리기"로 시작해 주세요.' }}
            onRow={({ c }) => ({
              onClick: () => navigate(`/oas/${c.latest_oa.oa_id}`),
              style: { cursor: 'pointer' },
            })}
          />
        </div>
        <p className="label2 t3" style={{ margin: 0 }}>
          제출기일은 통지서에서 읽은 글자예요. 기간연장은 반영하지 않으니 법적 기한은 사건 안에서 직접 확인해 주세요.
        </p>
      </section>
    </main>
  )
}
