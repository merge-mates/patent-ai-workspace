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
  CreatedOA,
  LegalAnswer,
  LegalChatView,
  UploadedDocument,
  OADetail,
  OAResultResponse,
  RunStatus,
  CreatedRun,
} from '../types/provisional/case'
import { ApiError } from './errors'
import { getJson, postForm, postJson, sendJson } from './http'
import { clearMockKeys, mockApi } from './mock'

// 화면은 api 한 곳만 쓰게 mock 저장 지우기도 여기서 내보낸다
export { resetMockStorage } from './mock'

export const API_MODE = import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'server'

// 서버 모드면 옛 mock 값(고른 방향·고친 초안·실행 흉내)이 브라우저에 남아 있지 않게 모듈을 불러올 때 지운다 (D6)
if (API_MODE === 'server') clearMockKeys()

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
  // 법률 질문 (필드는 F2 설계 때 바뀔 수 있음): chatId가 없으면 대화를 새로 만들고, 있으면 그 대화에 이어 묻는다
  // (질문마다 새 대화를 만들면 두 번째 질문부터 앞 맥락이 끊긴다)
  askLegal: async (q, chatId): Promise<LegalAnswer> => {
    const id = chatId ?? (await postJson<{ chat_id: string }>('/legal-chats', {})).chat_id
    const answer = await postJson<LegalEvidenceBundle>(`/legal-chats/${encodeURIComponent(id)}/messages`, q)
    return { chat_id: id, answer }
  },
  getDirections: (oaId) => getJson<DirectionCandidates[]>(`/oas/${oaId}/directions`),
  selectDirection: (unitId, candidateId) =>
    sendJson<DirectionCandidates>('PUT', `/directions/${encodeURIComponent(unitId)}/selection`, {
      candidate_id: candidateId,
    }),
  getCaseCheck: (oaId) => getJson<CaseCheck>(`/oas/${oaId}/case-check`),
  getDrafts: (oaId) => getJson<DraftsWithCheck>(`/oas/${oaId}/drafts`),
  patchDraft: (draftId, patch) => sendJson<DraftsWithCheck>('PATCH', `/drafts/${draftId}`, patch),
  getRun: (runId) => getJson<RunStatus>(`/runs/${encodeURIComponent(runId)}`),
  cancelRun: (runId) => postJson<RunStatus>(`/runs/${encodeURIComponent(runId)}/cancel`, {}),
  createCase: (file) => {
    const form = new FormData()
    form.append('file', file)
    return postForm<CreatedCase>('/cases', form)
  },
  // POST /cases/{id}/oas: 같은 사건의 다음 OA를 올리고 실행을 시작한다
  createOA: (caseId, file) => {
    const form = new FormData()
    form.append('file', file)
    return postForm<CreatedOA>(`/cases/${encodeURIComponent(caseId)}/oas`, form)
  },
  // POST /cases/{id}/documents: 조회하지 못한 자료를 올린다 ("올려 주세요"). 응답 모양은 명세에 없다
  uploadDocument: (caseId, file) => {
    const form = new FormData()
    form.append('file', file)
    return postForm<UploadedDocument>(`/cases/${encodeURIComponent(caseId)}/documents`, form)
  },
  // POST /oas/{oa_id}/runs: 다시 돌리기. 명세에는 "다시 확인 필요가 붙은 판단 단위만" 고르는 말이 있으나
  // 요청 필드가 없어 빈 본문으로 보낸다(전체 실행). 필드가 정해지면 인자를 더한다
  rerunOA: (oaId) => postJson<CreatedRun>(`/oas/${encodeURIComponent(oaId)}/runs`, {}),
  // GET /legal-chats/{id}: 대화 보기 (응답 모양 미정)
  getLegalChat: (chatId) => getJson<LegalChatView>(`/legal-chats/${encodeURIComponent(chatId)}`),
}

export const api = API_MODE === 'mock' ? mockApi : httpApi
