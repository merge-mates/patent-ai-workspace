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
import type { CaseCheck, DraftsWithCheck } from './types/provisional/pending'

export async function casesLoader(): Promise<CaseSummary[]> {
  return api.listCases()
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
  // 실행이 아직 안 끝났거나(404 result_not_ready) 서버에 엔드포인트가 아직 없으면 null
  oaResult: OAResultResponse | null
  // 사건 자료 목록이 아직 없거나 서버에 엔드포인트가 아직 없으면 null
  materials: CaseMaterials | null
  // API v0에 목록이 없거나 아직 없으면 null (개수만, 또는 모름)
  reviewItems: ReviewItem[] | null
  // 원문 쪽 글자를 못 받으면 null (원문 보기에서 알린다)
  document: PageText | null
}

export async function oaLoader({ params }: LoaderFunctionArgs): Promise<OALoaderData> {
  const oa = await api.getOA(params.oaId!)
  const [oaResult, materials, reviewItems, document] = await Promise.all([
    api.getOAResult(oa.oa_id).catch(missingAsNull),
    api.getMaterials(oa.case_id).catch(missingAsNull),
    // 목록 엔드포인트가 API v0에 없거나 아직 없을 때만 null. 다른 오류는 오류 화면으로
    api.getReviewItems(oa.case_id).catch((e: unknown) => {
      if (e instanceof ApiError && e.code === 'not_in_api_v0') return null
      return missingAsNull(e)
    }),
    // 원문 쪽 글자는 어떤 오류든 null (원문 보기에서 "받지 못함"으로 알린다)
    oa.document_id ? api.getDocument(oa.document_id).catch(() => null) : Promise.resolve(null),
  ])
  return { oa, oaResult, materials, reviewItems, document }
}

// 결과가 아직 없음(404 result_not_ready)만 null로 받고, 다른 오류는 그대로 올린다 (대비·초안 화면용)
function notReadyAsNull(e: unknown): null {
  if (isNotReady(e)) return null
  throw e
}

// "아직 없음"만 null로 받고, 다른 오류는 그대로 올린다 (조용히 삼키지 않는다).
// 아직 없음 = 404 result_not_ready, 또는 서버에 그 엔드포인트가 아직 없어서 나는 404 (code not_found)
function missingAsNull(e: unknown): null {
  if (isNotReady(e) || (e instanceof ApiError && e.code === 'not_found')) return null
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
