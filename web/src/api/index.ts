// 서버를 부르는 곳은 여기 한 곳이다. 화면은 이 api 객체만 쓴다.
// VITE_API_MODE=mock 이면 fixture(mock.ts), 아니면 서버(/api/*).
import type { CaseMaterials } from '../types/generated/CaseMaterials'
import type { PageText } from '../types/generated/PageText'
import type { ReviewItem } from '../types/generated/ReviewItem'
import type {
  CaseDetail,
  CaseSummary,
  CreatedCase,
  OADetail,
  OAResultResponse,
} from '../types/provisional/case'
import { ApiError } from './errors'
import { getJson, postForm } from './http'
import { mockApi } from './mock'

export const API_MODE = import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'server'

const httpApi: typeof mockApi = {
  listCases: () => getJson<CaseSummary[]>('/cases'),
  getCase: (caseId) => getJson<CaseDetail>(`/cases/${caseId}`),
  getOA: (oaId) => getJson<OADetail>(`/oas/${oaId}`),
  getOAResult: (oaId) => getJson<OAResultResponse>(`/oas/${oaId}/oa-result`),
  getMaterials: (caseId) => getJson<CaseMaterials>(`/cases/${caseId}/materials`),
  // API v0에는 검토할 사항 목록 엔드포인트가 없다 (개수만 materials.review_items_count).
  // 목록을 지어내지 않고 알린다. 화면은 개수만 보인다.
  getReviewItems: async (): Promise<ReviewItem[]> => {
    throw new ApiError('not_in_api_v0', '검토할 사항 목록은 API v0에 아직 없음', 0)
  },
  getDocument: (documentId) => getJson<PageText>(`/documents/${documentId}`),
  createCase: (file) => {
    const form = new FormData()
    form.append('file', file)
    return postForm<CreatedCase>('/cases', form)
  },
}

export const api = API_MODE === 'mock' ? mockApi : httpApi
