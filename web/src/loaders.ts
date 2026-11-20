// 화면에 들어가기 전에 데이터를 받는 곳 (react-router loader). 화면 부품 안에서 따로 부르지 않는다.
import { redirect, type LoaderFunctionArgs } from 'react-router'
import { api } from './api'
import { ApiError, isNotReady } from './api/errors'
import type { CaseMaterials } from './types/generated/CaseMaterials'
import type { PageText } from './types/generated/PageText'
import type { ReviewItem } from './types/generated/ReviewItem'
import type { ClarityReview } from './types/generated/ClarityReview'
import type { ComparisonTable } from './types/generated/ComparisonTable'
import type { DirectionCandidates } from './types/generated/DirectionCandidates'
import type { JudgmentUnit } from './types/generated/JudgmentUnit'
import type { LegalEvidenceBundle } from './types/generated/LegalEvidenceBundle'
import type { CaseSummary, OADetail, OAResultResponse } from './types/provisional/case'
import type { CaseListExtra } from './types/provisional/caseListExtra'
import type { CaseCheck, DraftsWithCheck } from './types/provisional/pending'
import { directTodos, pickFocusCase } from './todos'

export interface CasesLoaderData {
  cases: CaseSummary[]
  // case_id → 표에 더 보이는 값. 서버 모드에서는 비어 있다 (칸마다 "모름")
  extras: Record<string, CaseListExtra>
  // "오늘 먼저 볼 사건": 사건과 직접 할 일 앞 세 개 제목. 알려진 사건이 없으면 null
  focus: { case: CaseSummary; titles: string[] } | null
}

export async function casesLoader(): Promise<CasesLoaderData> {
  const [cases, extraList] = await Promise.all([api.listCases(), api.listCaseExtras()])
  const extras = Object.fromEntries(extraList.map((e) => [e.case_id, e]))
  const top = pickFocusCase(cases, new Map(Object.entries(extras)))
  if (top === null) return { cases, extras, focus: null }
  // 한 건만 제목이 필요해서 그 사건만 작업대 데이터를 받는다
  const d = await loadOA(top.latest_oa.oa_id)
  const todos = directTodos(d) ?? []
  return { cases, extras, focus: { case: top, titles: todos.slice(0, 3).map((t) => t.title) } }
}

// /cases/:caseId → 그 사건의 가장 최근 OA 작업대로
export async function caseLoader({ params }: LoaderFunctionArgs) {
  const c = await api.getCase(params.caseId!)
  const latest = c.oas.at(-1)
  if (!latest) throw new Error('이 사건에 OA가 없습니다')
  return redirect(`/oas/${latest.oa_id}`)
}

export interface OALoaderData {
  oa: OADetail
  // 실행이 아직 안 끝났으면 null (404 result_not_ready)
  oaResult: OAResultResponse | null
  // 사건 자료 목록이 아직 없으면 null
  materials: CaseMaterials | null
  // API v0에 목록이 없거나 아직 없으면 null (개수만, 또는 모름)
  reviewItems: ReviewItem[] | null
  // 원문 쪽 글자를 못 받으면 null (원문 보기에서 알린다)
  document: PageText | null
  // 대응 방향 묶음 (직접 할 일에서 방향을 이미 고른 묶음을 빼려고). 결과가 아직 없으면 []
  directions: DirectionCandidates[]
}

export function oaLoader({ params }: LoaderFunctionArgs): Promise<OALoaderData> {
  return loadOA(params.oaId!)
}

// 사건 작업대에 필요한 것을 한 번에 받는다 (사건 목록의 "오늘 먼저 볼 사건"도 쓴다)
async function loadOA(oaId: string): Promise<OALoaderData> {
  const oa = await api.getOA(oaId)
  const [oaResult, materials, reviewItems, document, directions] = await Promise.all([
    api.getOAResult(oa.oa_id).catch((e: unknown) => {
      if (isNotReady(e)) return null
      throw e
    }),
    api.getMaterials(oa.case_id).catch(notReadyAsNull),
    // 목록 엔드포인트가 API v0에 없거나 아직 없을 때만 null. 다른 오류는 오류 화면으로
    api.getReviewItems(oa.case_id).catch((e: unknown) => {
      if (e instanceof ApiError && e.code === 'not_in_api_v0') return null
      return notReadyAsNull(e)
    }),
    oa.document_id ? api.getDocument(oa.document_id).catch(() => null) : Promise.resolve(null),
    // 방향 결과가 아직 없으면 빈 목록 (고른 묶음이 없는 것으로 본다)
    api.getDirections(oa.oa_id).catch((e: unknown) => {
      if (isNotReady(e)) return []
      throw e
    }),
  ])
  return { oa, oaResult, materials, reviewItems, document, directions }
}

// 결과가 아직 없음(404 result_not_ready)만 null로 받고, 다른 오류는 그대로 올린다
function notReadyAsNull(e: unknown): null {
  if (isNotReady(e)) return null
  throw e
}

export interface CompareLoaderData {
  // 판단 단위 결과가 아직 없으면 null (실행 중, 404 result_not_ready)
  units: JudgmentUnit[] | null
  comparisons: ComparisonTable[]
  clarity: ClarityReview[]
  legal: LegalEvidenceBundle[]
}

// 3 대비와 근거: 판단 단위 · 대비표 · 명확성 문구 검토 · 법률 근거
export async function compareLoader({ params }: LoaderFunctionArgs): Promise<CompareLoaderData> {
  const oaId = params.oaId!
  // 결과가 아직 없음(result_not_ready)만 "없음"으로 받고, 다른 오류는 오류 화면으로
  const notReady = <T,>(fallback: T) => (e: unknown): T => {
    if (isNotReady(e)) return fallback
    throw e
  }
  const [units, comparisons, clarity, legal] = await Promise.all([
    api.getUnits(oaId).catch(notReady(null)),
    api.getComparisons(oaId).catch(notReady([])),
    api.getClarityReviews(oaId).catch(notReady([])),
    api.getLegalEvidence(oaId).catch(notReady([])),
  ])
  return { units, comparisons, clarity, legal }
}

export interface DirectionsLoaderData {
  units: JudgmentUnit[]
  directions: DirectionCandidates[]
  // 아직 없으면 null (확인되지 않음으로 보인다)
  caseCheck: CaseCheck | null
}

// 4 대응 방향: 묶음마다 후보 + 사건 전체 검사
export async function directionsLoader({ params }: LoaderFunctionArgs): Promise<DirectionsLoaderData> {
  const oaId = params.oaId!
  const [units, directions, caseCheck] = await Promise.all([
    api.getUnits(oaId),
    api.getDirections(oaId),
    api.getCaseCheck(oaId).catch(notReadyAsNull),
  ])
  return { units, directions, caseCheck }
}

export interface DraftsLoaderData {
  // 초안이 아직 없으면 null (404 result_not_ready)
  drafts: DraftsWithCheck | null
  // 지금 선택: 초안이 바탕으로 삼은 선택과 다른지 본다
  directions: DirectionCandidates[]
  caseCheck: CaseCheck | null
}

// 5 의견서·보정 초안
export async function draftsLoader({ params }: LoaderFunctionArgs): Promise<DraftsLoaderData> {
  const oaId = params.oaId!
  const [drafts, directions, caseCheck] = await Promise.all([
    api.getDrafts(oaId).catch(notReadyAsNull),
    api.getDirections(oaId),
    api.getCaseCheck(oaId).catch(notReadyAsNull),
  ])
  return { drafts, directions, caseCheck }
}
