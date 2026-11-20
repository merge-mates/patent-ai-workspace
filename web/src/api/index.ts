// 서버를 부르는 곳은 여기 한 곳이다. 화면은 이 api 객체만 쓴다.
// VITE_API_MODE=mock 이면 fixture(mock.ts), 아니면 서버(/api/*).
import type { ClarityReview } from '../types/generated/ClarityReview'
import type { ComparisonTable } from '../types/generated/ComparisonTable'
import type { DirectionCandidates } from '../types/generated/DirectionCandidates'
import type { JudgmentUnit } from '../types/generated/JudgmentUnit'
import type { LegalEvidenceBundle } from '../types/generated/LegalEvidenceBundle'
import type { CaseListExtra } from '../types/provisional/caseListExtra'
import type { CaseCheck, DraftsWithCheck } from '../types/provisional/pending'
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
import { getJson, postForm, postJson, sendJson } from './http'
import { mockApi } from './mock'

export const API_MODE = import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'server'

const httpApi: typeof mockApi = {
  listCases: () => getJson<CaseSummary[]>('/cases'),
  // API v0 사건 목록에 제출기일 글자·단계·직접 할 일 칸이 없다. 빈 목록 = 모든 사건의 칸이 "모름"
  listCaseExtras: async (): Promise<CaseListExtra[]> => [],
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
  getUnits: (oaId) => getJson<JudgmentUnit[]>(`/oas/${oaId}/units`),
  getComparisons: (oaId) => getJson<ComparisonTable[]>(`/oas/${oaId}/comparisons`),
  getClarityReviews: (oaId) => getJson<ClarityReview[]>(`/oas/${oaId}/clarity-reviews`),
  getLegalEvidence: (oaId) => getJson<LegalEvidenceBundle[]>(`/oas/${oaId}/legal-evidence`),
  // 법률 질문: 대화를 만들고 질문을 보낸다 (필드는 F2 설계 때 바뀔 수 있음)
  askLegal: async (q) => {
    const chat = await postJson<{ chat_id: string }>('/legal-chats', {})
    return postJson<LegalEvidenceBundle>(`/legal-chats/${chat.chat_id}/messages`, q)
  },
  getDirections: (oaId) => getJson<DirectionCandidates[]>(`/oas/${oaId}/directions`),
  selectDirection: (unitId, candidateId) =>
    sendJson<DirectionCandidates>('PUT', `/directions/${encodeURIComponent(unitId)}/selection`, {
      candidate_id: candidateId,
    }),
  getCaseCheck: (oaId) => getJson<CaseCheck>(`/oas/${oaId}/case-check`),
  getDrafts: (oaId) => getJson<DraftsWithCheck>(`/oas/${oaId}/drafts`),
  patchDraft: (draftId, patch) => sendJson<DraftsWithCheck>('PATCH', `/drafts/${draftId}`, patch),
  createCase: (file) => {
    const form = new FormData()
    form.append('file', file)
    return postForm<CreatedCase>('/cases', form)
  },
}

export const api = API_MODE === 'mock' ? mockApi : httpApi
