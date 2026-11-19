// 화면에 들어가기 전에 데이터를 받는 곳 (react-router loader). 화면 부품 안에서 따로 부르지 않는다.
import { redirect, type LoaderFunctionArgs } from 'react-router'
import { api } from './api'
import { isNotReady } from './api/errors'
import type { CaseMaterials } from './types/generated/CaseMaterials'
import type { PageText } from './types/generated/PageText'
import type { ReviewItem } from './types/generated/ReviewItem'
import type { CaseSummary, OADetail, OAResultResponse } from './types/provisional/case'

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
  // 실행이 아직 안 끝났으면 null (404 result_not_ready)
  oaResult: OAResultResponse | null
  materials: CaseMaterials
  // API v0에 목록이 없으면 null (개수만 보임)
  reviewItems: ReviewItem[] | null
  // 원문 쪽 글자를 못 받으면 null (원문 보기에서 알린다)
  document: PageText | null
}

export async function oaLoader({ params }: LoaderFunctionArgs): Promise<OALoaderData> {
  const oa = await api.getOA(params.oaId!)
  const [oaResult, materials, reviewItems, document] = await Promise.all([
    api.getOAResult(oa.oa_id).catch((e: unknown) => {
      if (isNotReady(e)) return null
      throw e
    }),
    api.getMaterials(oa.case_id),
    api.getReviewItems(oa.case_id).catch(() => null),
    oa.document_id ? api.getDocument(oa.document_id).catch(() => null) : Promise.resolve(null),
  ])
  return { oa, oaResult, materials, reviewItems, document }
}
