// "직접 할 일" 만들기 (순수 함수). 새 결과를 만들지 않고 이미 있는 것만 모은다:
// 검토할 사항(ReviewItem) 중 사람이 할 일 + 고정 한 줄 "제출기일 직접 확인". (결정 D1)
import { articleLabel, lookupResultLabel } from './labels'
import type { CaseMaterials } from './types/generated/CaseMaterials'
import type { DirectionCandidates } from './types/generated/DirectionCandidates'
import type { OAResult } from './types/generated/OAResult'
import type { ReviewItem } from './types/generated/ReviewItem'
import type { CaseListExtra } from './types/provisional/caseListExtra'
import type { CaseSummary } from './types/provisional/case'

// "가기" 버튼이 하는 일: 원문 판을 그 쪽으로 / 정리 단계의 그 자리로 / 다른 단계로
export type TodoGo =
  | { kind: 'source'; page: number | null; text: string | null; label: string }
  | { kind: 'anchor'; id: string; label: string }
  | { kind: 'route'; path: string; label: string }

export interface DirectTodo {
  key: string
  title: string
  desc: string
  go: TodoGo
}

export interface TodoInput {
  // 목록을 모르면 null → 개수도 모름 (0으로 보이지 않게)
  reviewItems: ReviewItem[] | null
  materials: CaseMaterials | null
  oaResult: { result: OAResult } | null
  // 대응 방향 결과를 못 받았으면 null → 방향 고르기를 셀 수 없어 개수도 모름
  directions: DirectionCandidates[] | null
}

// target은 `oa_result[0].rejections[3]` 꼴과 `oa_result[<oa_id>].rejections[3]` 꼴이 섞여 있다. 둘 다 받는다
const rejectionIndex = (target: string): number | null => {
  const m = /^oa_result\[[^\]]*\]\.rejections\[(\d+)\]/.exec(target)
  return m ? Number(m[1]) : null
}
const isCitationTarget = (target: string) => /\.citations\[\d+\]/.test(target)
const missingIndex = (target: string): number | null => {
  const m = /^materials\.missing\[(\d+)\]$/.exec(target)
  return m ? Number(m[1]) : null
}

// `oa_1:42-4-2:c7` → "제42조제4항제2호 · 청구항 7" (모양이 다르면 ID 그대로)
function unitText(unitId: string): string {
  const m = /^[^:]+:([^:]+):c(\d+)$/.exec(unitId)
  return m ? `${articleLabel(m[1])} · 청구항 ${m[2]}` : unitId
}

export function directTodos(input: TodoInput): DirectTodo[] | null {
  const { reviewItems, materials, oaResult, directions } = input
  if (reviewItems === null || directions === null) return null
  const r = oaResult?.result ?? null
  const todos: DirectTodo[] = []

  // 제출기일은 늘 한 줄: 법적 기한이라 AI가 확정하지 않고 원문 글자만 보인다
  const due = r?.response_due ?? null
  todos.push({
    key: 'due',
    title: due?.raw_text ? `제출기일 ${due.raw_text} 직접 확인` : '제출기일 직접 확인',
    desc: '법적 기한이라 자동으로 확정하지 않아요. 기간연장은 반영하지 않아요',
    go: {
      kind: 'source',
      page: due?.page ?? null,
      text: due?.raw_text ?? null,
      label: due?.page ? `통지서 ${due.page}쪽` : '통지서 보기',
    },
  })

  reviewItems.forEach((item, i) => {
    if (item.kind === 'missing_material') {
      // 올려 달라고 한 자료만 (지원 안 하는 나라는 올릴 곳이 없어 거절이유 줄이 대신 보인다)
      const idx = missingIndex(item.target)
      const row = idx === null ? undefined : materials?.missing[idx]
      if (!row?.ask_upload) return
      todos.push({
        key: `m-${i}`,
        title: `${row.what} 올리기`,
        desc: `${lookupResultLabel[row.lookup_result]}라 대비 일부를 보류했어요`,
        go: { kind: 'anchor', id: 'materials', label: '자료 보기' },
      })
    } else if (item.kind === 'needs_human_review') {
      const idx = rejectionIndex(item.target)
      const rej = idx === null ? undefined : r?.rejections[idx]
      if (rej && !isCitationTarget(item.target)) {
        todos.push({
          key: `r-${i}`,
          title: `거절이유 ${rej.no} 직접 검토`,
          desc: `AI가 다루지 않는 거절이유예요 (특허법 ${articleLabel(rej.article.value)})`,
          go: { kind: 'anchor', id: `rejection-${rej.no}`, label: '거절이유 보기' },
        })
      } else {
        todos.push({
          key: `r-${i}`,
          title: `직접 검토: ${item.label}`,
          desc: item.reason,
          go: { kind: 'anchor', id: rej ? `rejection-${rej.no}` : 'rejections', label: '거절이유 보기' },
        })
      }
    }
  })

  // 방향 고르기: 서버 검토할 사항 줄(모양이 다름)을 쓰지 않고 대응 방향 결과에서 바로 센다.
  // 직접 판단 표시가 있고 아직 안 고른(selection === null) 묶음마다 한 줄
  for (const d of directions) {
    if (!d.flags.includes('needs_human_judgment') || d.selection !== null) continue
    todos.push({
      key: `j-${d.unit_id}`,
      title: `방향 고르기: ${unitText(d.unit_id)}`,
      desc: '확신이 낮아 미리 고르지 않았어요',
      go: { kind: 'route', path: '/directions', label: '고르러 가기' },
    })
  }
  return todos
}

// 제출기일 원문 글자 → 정렬 키. `2099.04.10.` · `2027. 1. 10.` 꼴만 읽고, 못 읽으면 null (뒤로)
// 정렬에만 쓰고 화면에는 원문 글자를 그대로 보인다 (남은 날 계산은 하지 않는다)
export function dueSortKey(raw: string | null): number | null {
  const m = raw ? /^\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})/.exec(raw) : null
  return m ? Number(m[1]) * 10000 + Number(m[2]) * 100 + Number(m[3]) : null
}

// "오늘 먼저 볼 사건" 한 건: 직접 할 일이 있다고 알려진 사건 중
// 사람 기다림 먼저 → 제출기일 이른 순(원문 글자를 못 읽으면 뒤) → 직접 할 일 많은 순
export function pickFocusCase(cases: CaseSummary[], extras: Map<string, CaseListExtra>): CaseSummary | null {
  const known = cases.filter((c) => (extras.get(c.case_id)?.todo_count ?? 0) > 0)
  const rank = (c: CaseSummary) => {
    const e = extras.get(c.case_id)!
    return [c.run_state === 'waiting_for_human' ? 0 : 1, dueSortKey(e.response_due_raw) ?? Infinity, -(e.todo_count ?? 0)]
  }
  known.sort((a, b) => {
    const ra = rank(a)
    const rb = rank(b)
    for (let i = 0; i < ra.length; i++) if (ra[i] !== rb[i]) return ra[i] < rb[i] ? -1 : 1
    return 0
  })
  return known[0] ?? null
}
