// 서버를 부르는 곳은 여기 한 곳이다. 화면은 이 api 객체만 쓴다.
// VITE_API_MODE=mock 이면 fixture(mock.ts), 아니면 서버(/api/*).
import type { ClarityReview } from '../types/generated/ClarityReview'
import type { ComparisonTable } from '../types/generated/ComparisonTable'
import type { DirectionCandidates } from '../types/generated/DirectionCandidates'
import type { JudgmentUnit } from '../types/generated/JudgmentUnit'
import type { LegalEvidenceBundle } from '../types/generated/LegalEvidenceBundle'
import type { CaseListExtra } from '../types/provisional/caseListExtra'
import type { Drafts } from '../types/generated/Drafts'
import type { CaseCheck, DraftPatch } from '../types/provisional/pending'
import type { CaseMaterials } from '../types/generated/CaseMaterials'
import type { PageText } from '../types/generated/PageText'
import type { PlanIssue } from '../types/generated/PlanIssue'
import type { ExtraClaim } from '../types/generated/ExtraClaim'
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
  SelectionResult,
  NumberEnteredOut,
  ConfirmationOut,
} from '../types/provisional/case'
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
const getDraftsResult = async (oaId: string): Promise<Drafts> => {
  const body = await getJson<ResultEnvelope<Drafts | null>>(`/oas/${oaId}/drafts`)
  if (body.result === null) {
    // 서버 계약 위반(초안 없음인데 이유 없음)은 경고를 남긴다
    if (!body.empty_reason) console.warn(`[api] /oas/${oaId}/drafts: 초안이 없는데 empty_reason이 없음`)
    throw new ApiError('result_not_ready', body.empty_reason ?? '초안이 없습니다', 200)
  }
  return body.result
}

// 사건 단위 보정안(이 브랜치): 초안 API가 함께 주는 1번 안 전략 글·다른 안·코드 검사 표시.
// 보정 청구항 자체는 Drafts.claims에 있다. 이 보정안을 쓰지 않은 실행이면 null
export interface AmendmentPlanInfo {
  strategy: string
  alternatives: string[]
  checks: PlanIssue[]
  // 2·3번 안에서만 고친 항 (검토해 볼 항)
  extra: ExtraClaim[]
}
interface DraftsExtra {
  amendment_strategy: string | null
  amendment_alternatives: string[]
  amendment_checks: PlanIssue[]
  amendment_extra: ExtraClaim[]
}
const getAmendmentPlanResult = async (oaId: string): Promise<AmendmentPlanInfo | null> => {
  const body = await getJson<ResultEnvelope<Drafts | null> & DraftsExtra>(`/oas/${oaId}/drafts`)
  if (body.amendment_strategy === null || body.amendment_strategy === undefined) return null
  return { strategy: body.amendment_strategy, alternatives: body.amendment_alternatives ?? [], checks: body.amendment_checks ?? [], extra: body.amendment_extra ?? [] }
}
type FrontendApi = Omit<typeof mockApi, 'getDrafts' | 'patchDraft' | 'getAmendmentPlan'> & {
  getDrafts: (oaId: string) => Promise<Drafts>
  getAmendmentPlan: (oaId: string) => Promise<AmendmentPlanInfo | null>
  patchDraft: (draftId: string, patch: DraftPatch) => Promise<Drafts>
}

const httpApi: FrontendApi = {
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
  // 후보 id 또는 직접 쓴 방향 글 하나를 보낸다. 응답의 run_id는 초안만 다시 만드는 새 작은 실행
  selectDirection: (unitId, body) =>
    sendJson<SelectionResult>('PUT', `/directions/${encodeURIComponent(unitId)}/selection`, body),
  getCaseCheck: (oaId) => getJson<CaseCheck>(`/oas/${oaId}/case-check`),
  getDrafts: (oaId) => getDraftsResult(oaId),
  getAmendmentPlan: (oaId) => getAmendmentPlanResult(oaId),
  patchDraft: (draftId, patch) => sendJson<Drafts>('PATCH', `/drafts/${draftId}`, patch),
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
  // 출원번호 입력 (PATCH /cases/{id}, #70): 기다리던 같은 실행이 이어 돈다. 응답 run_id를 폴링에 넣는다
  setApplicationNumber: (caseId, applicationNumber) =>
    sendJson<NumberEnteredOut>('PATCH', `/cases/${encodeURIComponent(caseId)}`, { application_number: applicationNumber }),
  // 발송번호 입력 (PATCH /oas/{id}, #70): 기다리던 같은 실행이 이어 돈다. 응답 run_id를 폴링에 넣는다
  setDispatchNumber: (oaId, dispatchNumber) =>
    sendJson<NumberEnteredOut>('PATCH', `/oas/${encodeURIComponent(oaId)}`, { dispatch_number: dispatchNumber }),
  // 정리 결과 "맞아요" (#70): GET은 지금 보이는 정리의 확인 상태(없으면 confirmed_at null), PUT은 확인 남기기(다시 보내면 시각만 새로)
  getOAResultConfirmation: (oaId) => getJson<ConfirmationOut>(`/oas/${encodeURIComponent(oaId)}/oa-result/confirmation`),
  // PUT 본문에 사람이 본 정리의 run_id를 보낸다. 그 사이 정리가 바뀌었으면 서버가 409 stale_result로 막는다 (#311)
  confirmOAResult: (oaId, runId) =>
    sendJson<ConfirmationOut>('PUT', `/oas/${encodeURIComponent(oaId)}/oa-result/confirmation`, { run_id: runId }),
  // GET /legal-chats/{id}: 대화 보기
  getLegalChat: (chatId) => getJson<LegalChatView>(`/legal-chats/${encodeURIComponent(chatId)}`),
}

export const api: FrontendApi = API_MODE === 'mock' ? mockApi : httpApi
