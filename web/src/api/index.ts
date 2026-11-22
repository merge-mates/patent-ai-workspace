// 서버를 부르는 곳은 여기 한 곳이다. 화면은 이 api 객체만 쓴다.
// VITE_API_MODE=mock 이면 fixture(mock.ts), 아니면 서버(/api/*).
import type { ClarityReview } from '../types/generated/ClarityReview'
import type { ComparisonTable } from '../types/generated/ComparisonTable'
import type { DirectionCandidates } from '../types/generated/DirectionCandidates'
import type { JudgmentUnit } from '../types/generated/JudgmentUnit'
import type { LegalEvidenceBundle } from '../types/generated/LegalEvidenceBundle'
import type { CaseListExtra } from '../types/provisional/caseListExtra'
import type { Drafts } from '../types/generated/Drafts'
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
  LegalChatAnswerResponse,
  LegalChatView,
  UploadedDocument,
  OADetail,
  OAResultResponse,
  RunStatus,
  CreatedRun,
} from '../types/provisional/case'
import { requireDraftCheck } from './draftCheck'
import { ApiError } from './errors'
import type { ResultList } from './resultList'
import { getJson, postForm, postJson, sendJson } from './http'
import { clearMockKeys, mockApi } from './mock'

// 화면은 api 한 곳만 쓰게 mock 저장 지우기도 여기서 내보낸다
export { resetMockStorage } from './mock'

export const API_MODE = import.meta.env.VITE_API_MODE === 'mock' ? 'mock' : 'server'

// 서버 모드면 옛 mock 값(고른 방향·고친 초안·실행 흉내)이 브라우저에 남아 있지 않게 모듈을 불러올 때 지운다 (D6)
if (API_MODE === 'server') clearMockKeys()

// F3·F4 결과 응답 모양 (#191): {oa_id, run_id, result, empty_reason}. result에 결과 스키마가 들어 있다.
// 단계를 넘겼거나 해당 거절이유가 없으면 result가 비고 empty_reason에 이유가 온다 (넘김: … / 보류: …)
interface ResultEnvelope<T> {
  oa_id: string
  run_id: string
  result: T
  empty_reason: string | null
}

// 결과 목록 받기: 목록과 빈 이유를 같이 돌려준다. 화면은 목록이 비면 이유를 보인다 ("0건"으로만 그리지 않음)
const getResult = async <T>(path: string): Promise<ResultList<T>> => {
  const body = await getJson<ResultEnvelope<T[]>>(path)
  // 서버 계약 위반(빈 목록인데 이유 없음)은 조용히 넘기지 않고 경고를 남긴다
  if (body.result.length === 0 && !body.empty_reason) console.warn(`[api] ${path}: 빈 목록인데 empty_reason이 없음`)
  return { items: body.result, emptyReason: body.empty_reason }
}

// 초안 받기: 초안이 없으면(모든 묶음 보류·F4 넘김) 지어내지 않고 "아직 없음"으로 알리며 이유를 싣는다
// 서버 Drafts에는 check 칸이 없으므로 형변환하지 않고 가드로 본다. 없으면 오류 화면 ("초안 검사 결과 없음")
const getDraftsResult = async (oaId: string): Promise<DraftsWithCheck> => {
  const body = await getJson<ResultEnvelope<Drafts | null>>(`/oas/${oaId}/drafts`)
  if (body.result === null) {
    // 서버 계약 위반(초안 없음인데 이유 없음)은 경고를 남긴다
    if (!body.empty_reason) console.warn(`[api] /oas/${oaId}/drafts: 초안이 없는데 empty_reason이 없음`)
    throw new ApiError('result_not_ready', body.empty_reason ?? '초안이 없습니다', 200)
  }
  return requireDraftCheck(body.result)
}

const httpApi: typeof mockApi = {
  listCases: () => getJson<CaseSummary[]>('/cases'),
  // API v0 사건 목록에 제출기일 글자·단계·직접 할 일 칸이 없다. 빈 목록 = 모든 사건의 칸이 "모름"
  listCaseExtras: async (): Promise<CaseListExtra[]> => [],
  getCase: (caseId) => getJson<CaseDetail>(`/cases/${caseId}`),
  getOA: (oaId) => getJson<OADetail>(`/oas/${oaId}`),
  getOAResult: (oaId) => getJson<OAResultResponse>(`/oas/${oaId}/oa-result`),
  // 서버 응답은 {case_id, run_id, result} 봉투다 (src/patent_ai/api/cases.py CaseMaterialsOut). 결과 스키마 ⑥은 result에 있다
  getMaterials: async (caseId) =>
    (await getJson<{ case_id: string; run_id: string | null; result: CaseMaterials }>(`/cases/${caseId}/materials`)).result,
  // 검토할 사항 목록만 따로 주는 엔드포인트는 없다 (목록은 사건 자료 ⑥의 review_items에 있다). 목록을 지어내지 않고 알린다
  getReviewItems: async (): Promise<ReviewItem[]> => {
    throw new ApiError('not_in_api_v0', '검토할 사항 목록은 API v0에 아직 없음', 0)
  },
  getDocument: (documentId) => getJson<PageText>(`/documents/${documentId}`),
  getUnits: (oaId) => getResult<JudgmentUnit>(`/oas/${oaId}/units`),
  getComparisons: (oaId) => getResult<ComparisonTable>(`/oas/${oaId}/comparisons`),
  getClarityReviews: (oaId) => getResult<ClarityReview>(`/oas/${oaId}/clarity-reviews`),
  getLegalEvidence: (oaId) => getResult<LegalEvidenceBundle>(`/oas/${oaId}/legal-evidence`),
  // 법률 질문: chatId가 없으면 대화를 새로 만들고, 있으면 그 대화에 이어 묻는다
  // (질문마다 새 대화를 만들면 두 번째 질문부터 앞 맥락이 끊긴다)
  // 서버 응답 {chat_id, no, scope_changed, result}의 result(법률 근거 묶음)가 화면의 answer다
  askLegal: async (q, chatId): Promise<LegalAnswer> => {
    const id = chatId ?? (await postJson<{ chat_id: string }>('/legal-chats', {})).chat_id
    const res = await postJson<LegalChatAnswerResponse>(`/legal-chats/${encodeURIComponent(id)}/messages`, q)
    return { chat_id: res.chat_id, answer: res.result, scope_changed: res.scope_changed }
  },
  getDirections: (oaId) => getResult<DirectionCandidates>(`/oas/${oaId}/directions`),
  selectDirection: (unitId, candidateId) =>
    sendJson<DirectionCandidates>('PUT', `/directions/${encodeURIComponent(unitId)}/selection`, {
      candidate_id: candidateId,
    }),
  getCaseCheck: (oaId) => getJson<CaseCheck>(`/oas/${oaId}/case-check`),
  getDrafts: (oaId) => getDraftsResult(oaId),
  // 고친 뒤 받은 초안도 같은 가드를 거친다
  patchDraft: async (draftId, patch) => requireDraftCheck(await sendJson<Drafts>('PATCH', `/drafts/${draftId}`, patch)),
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
  // POST /cases/{id}/documents: 조회하지 못한 자료를 올린다 ("올려 주세요").
  // what = 답하는 빠진 자료 (CaseMaterials.missing[].what 글자 그대로). 서버가 이 글자로 빠진 자료를 찾는다
  uploadDocument: (caseId, file, what) => {
    const form = new FormData()
    form.append('file', file)
    form.append('what', what)
    return postForm<UploadedDocument>(`/cases/${encodeURIComponent(caseId)}/documents`, form)
  },
  // POST /oas/{oa_id}/runs: 다시 돌리기. 명세에는 "다시 확인 필요가 붙은 판단 단위만" 고르는 말이 있으나
  // 요청 필드가 없어 빈 본문으로 보낸다(전체 실행). 필드가 정해지면 인자를 더한다
  rerunOA: (oaId) => postJson<CreatedRun>(`/oas/${encodeURIComponent(oaId)}/runs`, {}),
  // 출원번호 입력 (PATCH /cases/{id}, #70): 기다리던 같은 실행이 이어 돈다 (화면은 그 run_id를 다시 받음)
  setApplicationNumber: async (caseId, applicationNumber) => {
    await sendJson<unknown>('PATCH', `/cases/${encodeURIComponent(caseId)}`, {
      application_number: applicationNumber,
    })
  },
  // GET /legal-chats/{id}: 대화 보기
  getLegalChat: (chatId) => getJson<LegalChatView>(`/legal-chats/${encodeURIComponent(chatId)}`),
}

export const api = API_MODE === 'mock' ? mockApi : httpApi
