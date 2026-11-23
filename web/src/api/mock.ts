// mock 모드 (VITE_API_MODE=mock): 서버 없이 fixture를 돌려준다.
// fixture는 scripts/web_fixtures.py가 가짜 통지서 + 기록된 모델 응답으로 만든 것 (git에 있음).
// 시연용 실제 결과(web/.demo/*.json, git 밖)는 VITE_DEMO=1일 때만 더 읽는다.
import { HUMAN_ENTERED_CHECKED } from '../labels'
import type { CaseMaterials } from '../types/generated/CaseMaterials'
import type { OAResult, RejectionKind } from '../types/generated/OAResult'
import type { PageText } from '../types/generated/PageText'
import type { ReviewItem } from '../types/generated/ReviewItem'
import type {
  CaseDetail,
  CaseSummary,
  CreatedCase,
  CreatedOA,
  LatestRun,
  LegalAnswer,
  LegalChatView,
  OADetail,
  OAResultResponse,
  RunStatus,
  CreatedRun,
  SelectionBody,
  SelectionResult,
  NumberEnteredOut,
  ConfirmationOut,
  UploadedDocument,
} from '../types/provisional/case'
import type { ClarityReview } from '../types/generated/ClarityReview'
import type { ComparisonTable } from '../types/generated/ComparisonTable'
import type { DirectionCandidates, DirectionSelection } from '../types/generated/DirectionCandidates'
import type { JudgmentUnit } from '../types/generated/JudgmentUnit'
import type { LegalEvidenceBundle } from '../types/generated/LegalEvidenceBundle'
import {
  exampleClarity,
  exampleComparisons,
  exampleLegal,
  exampleLegalAnswer,
  exampleUnits,
} from '../types/provisional/examples'
import type { CaseCheck, DraftPatch, DraftsWithCheck, LegalQuestion } from '../types/provisional/pending'
import { exampleCaseChecks, exampleDirections, exampleDrafts } from '../types/provisional/directionExamples'
import demoFiles from 'virtual:demo-results'
import type { CaseListExtra, CaseStage } from '../types/provisional/caseListExtra'
import { directTodos } from '../todos'
import { isApplicationNumberShape, isDispatchNumberShape } from '../numberShapes'
import { ApiError } from './errors'
import type { ResultList } from './resultList'

// fixture 한 묶음 = 사건 하나 + OA 하나
interface Bundle {
  case_id: string
  case_name: string
  last_opened_at: string
  oa_id: string
  run_id: string
  oa_result: OAResult
  // 시연용 결과처럼 모르면 null: "없음"으로 보이지 않게 (0건과 다름)
  materials: CaseMaterials | null
  review_items: ReviewItem[] | null
  document: PageText | null
}

const committed = Object.values(
  import.meta.glob<Bundle>('./fixtures/*.json', { eager: true, import: 'default' }),
)

// 시연용 결과는 OAResult 하나뿐이라 사건 자료·검토할 사항·원문은 "모름"(null)으로 둔다.
// 파일 목록은 vite.config.ts의 가상 모듈이 VITE_DEMO=1일 때만 만든다

let demoCache: Bundle[] | null = null

async function bundles(): Promise<Bundle[]> {
  if (import.meta.env.VITE_DEMO !== '1') return committed
  if (demoCache === null) {
    // 시연 파일은 OAResult로 저장된 것 (F1 결과)
    const results = (await Promise.all(Object.values(demoFiles).map((load) => load()))) as OAResult[]
    demoCache = results.map((r, i) => {
      const caseId = `demo_${i + 1}`
      return {
        case_id: caseId,
        case_name: `시연 사건 ${i + 1}`,
        last_opened_at: '2026-11-20T09:00:00',
        oa_id: `demo_oa_${i + 1}`,
        run_id: `demo_run_${i + 1}`,
        oa_result: r,
        materials: null,
        review_items: null,
        document: null,
      }
    })
  }
  return [...committed, ...demoCache]
}

async function byCase(caseId: string): Promise<Bundle> {
  const found = (await bundles()).find((b) => b.case_id === caseId)
  if (!found) throw new ApiError('case_not_found', '사건을 찾을 수 없습니다', 404)
  return found
}

async function byOA(oaId: string): Promise<Bundle> {
  const found = (await bundles()).find((b) => b.oa_id === oaId)
  if (!found) throw new ApiError('oa_not_found', 'OA를 찾을 수 없습니다', 404)
  return found
}

function summaryOf(b: Bundle): CaseSummary {
  const r = b.oa_result
  // 같은 종류는 한 번만 (표에서 꼬리표로 보인다)
  const kinds = [...new Set(r.rejections.map((x) => x.kind))] as RejectionKind[]
  return {
    case_id: b.case_id,
    case_name: b.case_name,
    application_number: r.application_number.raw_text ?? r.application_number.value ?? null,
    latest_oa: { oa_id: b.oa_id, notice_kind: r.notice_kind.value ?? null },
    rejection_kinds: kinds,
    run_state: runOf(b).state,
    status: r.status.value,
    review_items_count: b.review_items?.length ?? null,
    updated_at: b.last_opened_at,
  }
}

// 결과 목록 + 빈 이유. mock 예시에는 빈 이유가 없어서, 비면 서버가 이유를 모를 때 쓰는 글자를 그대로 쓴다 (지어내지 않음)
const MOCK_EMPTY_REASON = '확인되지 않음: 이 실행에 결과가 없음'
const listOf = <T,>(items: T[]): ResultList<T> => ({ items, emptyReason: items.length === 0 ? MOCK_EMPTY_REASON : null })

// 이번 화면 세션에서 올린 파일 (이름:크기). 409 흉내용
const uploadedKeys = new Set<string>()

export const mockApi = {
  async listCases(): Promise<CaseSummary[]> {
    return (await bundles()).map(summaryOf)
  },
  async getCase(caseId: string): Promise<CaseDetail> {
    const b = await byCase(caseId)
    return {
      case_id: b.case_id,
      case_name: b.case_name,
      oas: [{ oa_id: b.oa_id, notice_kind: b.oa_result.notice_kind.value ?? null }],
    }
  },
  async getOA(oaId: string): Promise<OADetail> {
    const b = await byOA(oaId)
    return {
      oa_id: b.oa_id,
      case_id: b.case_id,
      case_name: b.case_name,
      document_id: b.document?.document_id ?? null,
      latest_run: latestOf(runOf(b)),
    }
  },
  async getOAResult(oaId: string): Promise<OAResultResponse> {
    const b = await byOA(oaId)
    const runId = gateResult(b)
    return { oa_id: b.oa_id, run_id: runId, status: b.oa_result.status.value, result: withHumanNumber(b) }
  },
  async getMaterials(caseId: string): Promise<CaseMaterials> {
    const b = await byCase(caseId)
    gate(b, PHASE.materials)
    const m = b.materials
    if (!m) throw new ApiError('result_not_ready', '사건 자료 목록이 아직 없습니다', 404)
    return m
  },
  async getReviewItems(caseId: string): Promise<ReviewItem[]> {
    const b = await byCase(caseId)
    gateResult(b)
    if (!b.review_items) throw new ApiError('result_not_ready', '검토할 사항 목록이 아직 없습니다', 404)
    return b.review_items
  },
  // 사건 목록에 더 보이는 값 (fixture·예시에서 채운다). 서버 모드는 비어 있어 "모름"
  async listCaseExtras(): Promise<CaseListExtra[]> {
    return (await bundles()).map((b) => {
      flushPending(b)
      const todos = directTodos({
        reviewItems: b.review_items,
        materials: b.materials,
        oaResult: { result: b.oa_result },
        directions: directions[b.oa_id] ?? null,
      })
      return {
        case_id: b.case_id,
        response_due_raw: b.oa_result.response_due.raw_text,
        stage: stageOf(b.oa_id),
        // 방향 고르기를 못 센 사건은 개수를 "모름"으로 둔다 (적게 센 숫자를 정확한 값처럼 보이지 않게)
        todo_count: todos?.directionsKnown ? todos.todos.length : null,
      }
    })
  },
  async getDocument(documentId: string): Promise<PageText> {
    const found = (await bundles()).find((b) => b.document?.document_id === documentId)
    if (!found?.document) throw new ApiError('document_not_found', '원문을 찾을 수 없습니다', 404)
    return found.document
  },
  // ②③④는 스키마가 아직 없어 예시 데이터 (types/provisional/examples.ts)
  async getUnits(oaId: string): Promise<ResultList<JudgmentUnit>> {
    gateResult(await byOA(oaId))
    return listOf(exampleUnits[oaId] ?? [])
  },
  async getComparisons(oaId: string): Promise<ResultList<ComparisonTable>> {
    gateResult(await byOA(oaId))
    return listOf(ofOA(exampleComparisons, oaId))
  },
  async getClarityReviews(oaId: string): Promise<ResultList<ClarityReview>> {
    gateResult(await byOA(oaId))
    return listOf(ofOA(exampleClarity, oaId))
  },
  async getLegalEvidence(oaId: string): Promise<ResultList<LegalEvidenceBundle>> {
    gateResult(await byOA(oaId))
    return listOf(ofOA(exampleLegal, oaId))
  },
  // 이어 묻기: mock은 대화를 기억하지 않고 고정 chat_id만 돌려준다 (서버 모양만 맞춤)
  async askLegal(q: LegalQuestion, chatId?: string): Promise<LegalAnswer> {
    return { chat_id: chatId ?? MOCK_CHAT_ID, answer: exampleLegalAnswer(q) }
  },
  // ⑤ 대응 방향·초안: 사람이 고른 것·고친 것은 메모리 + localStorage에 남는다 (아래 저장 코드, "mock 처음으로"로 지움)
  async getDirections(oaId: string): Promise<ResultList<DirectionCandidates>> {
    const b = await byOA(oaId)
    flushPending(b)
    gateResult(b)
    return listOf(directions[oaId] ?? [])
  },
  // 방향을 고르면 서버처럼 초안만 다시 만드는 새 작은 실행이 생긴 것으로 흉내 낸다 (run_id를 돌려준다)
  async selectDirection(unitId: string, body: SelectionBody): Promise<SelectionResult> {
    const entry = Object.entries(directions).find(([, list]) => list.some((d) => d.unit_id === unitId))
    const found = entry?.[1].find((d) => d.unit_id === unitId)
    if (!entry || !found) throw new ApiError('unit_not_found', '판단 단위를 찾을 수 없습니다', 404)
    const b = await byOA(entry[0])
    flushPending(b)
    // 서버처럼 실행이 도는 동안은 못 고른다
    const now = runOf(b).state
    if (now === 'queued' || now === 'running') throw new ApiError('run_in_progress', '이미 진행 중인 실행이 있습니다', 409)
    // 서버와 같게: 후보 id 또는 직접 쓴 글, 정확히 하나 (빈 글·둘 다·둘 다 없음은 422 invalid_selection)
    const raw = body as { candidate_id?: string | null; written_direction?: string | null }
    const candidateId = raw.candidate_id ?? null
    const written = raw.written_direction ?? null
    if ((candidateId === null) === (written === null) || (written !== null && written.trim() === ''))
      throw new ApiError('invalid_selection', '후보 id나 직접 쓴 방향 중 하나만 보내야 합니다', 422)
    if (candidateId !== null && !found.candidates.some((c) => c.candidate_id === candidateId))
      throw new ApiError('candidate_not_found', '그 묶음의 후보가 아닙니다', 422)
    // PUT으로 저장한 선택은 1등과 같아도 "사람이 고름" (docs/api/README.md)
    // 작은 실행이 끝날 때까지 GET directions는 옛 선택을 준다: 고른 것은 그 실행에 묶어 두고 끝나면 반영한다
    // 사람 선택은 selection.origin 한 곳에만 둔다 (묶음 맨 위 origin은 ai_generated 그대로)
    const selection = selectionOf({ unitId, candidateId, written })
    // 그 OA에 작은 실행 시작: 앞 결과는 이어 보인다 (서버도 앞 실행 결과를 옮긴다)
    startRun(b, true, true)
    const run = loadRun(b.oa_id)
    if (run) saveRun(b.oa_id, { ...run, pending: [{ unitId, candidateId, written }] })
    return { unit_id: unitId, run_id: runOf(b).run_id, selection }
  },
  async getCaseCheck(oaId: string): Promise<CaseCheck> {
    gateResult(await byOA(oaId))
    // 예시가 없으면 "다루지 않은 거절이유 없음"처럼 지어내지 않고 결과 없음으로
    const check = exampleCaseChecks[oaId]
    if (!check) throw new ApiError('result_not_ready', '사건 전체 검사 결과가 아직 없습니다', 404)
    return check
  },
  async getDrafts(oaId: string): Promise<DraftsWithCheck> {
    const b = await byOA(oaId)
    flushPending(b)
    gateResult(b)
    const d = drafts[oaId]
    if (!d) throw new ApiError('result_not_ready', '초안이 아직 없습니다', 404)
    return d
  },
  async patchDraft(draftId: string, patch: DraftPatch): Promise<DraftsWithCheck> {
    const d = Object.values(drafts).find((x) => x.draft_id === draftId)
    if (!d) throw new ApiError('draft_not_found', '초안을 찾을 수 없습니다', 404)
    // AI 원본은 그대로 두고 사람이 고친 글만 바꾼다. AI 원문과 같아지면 고친 것이 아님
    if (patch.section !== undefined) {
      const sec = d.opinion.find((x) => x.key === patch.section)
      if (!sec) throw new ApiError('section_not_found', '의견서 칸을 찾을 수 없습니다', 400)
      sec.human_text = patch.text === sec.ai_text ? null : patch.text
      sec.origin = sec.human_text === null ? 'ai_generated' : 'human_edited' // 고친 글이 있으면 사람이 고친 것
    } else {
      const c = d.claims.find((x) => x.claim === patch.claim)
      // 보류한 청구항(초안 없음)은 고칠 수 없다
      if (!c || c.ai_text === null) throw new ApiError('claim_not_editable', '고칠 수 있는 보정 초안이 없습니다', 400)
      c.human_text = patch.text === c.ai_text ? null : patch.text
      c.origin = c.human_text === null ? 'ai_generated' : 'human_edited'
    }
    // 초안 전체도 고친 곳이 하나라도 있으면 사람이 고친 것
    recomputeDraftOrigin(d)
    saveDraft(d)
    return { ...d }
  },
  // 실행 상태: 시작 시각과 흐른 시간으로 만든다 (D5). 표에 없는 OA는 늘 끝남
  async getRun(runId: string): Promise<RunStatus> {
    const b = await byRun(runId)
    if (!b) throw new ApiError('run_not_found', '실행을 찾을 수 없습니다', 404)
    return { ...runOf(b), oa_id: b.oa_id, error: null, skipped_steps: [] }
  },
  async cancelRun(runId: string): Promise<RunStatus> {
    const b = await byRun(runId)
    if (!b) throw new ApiError('run_not_found', '실행을 찾을 수 없습니다', 404)
    const run = loadRun(b.oa_id)
    // 이미 끝난 실행은 취소할 수 없다 (끝난 것을 취소로 바꾸지 않는다)
    if (run && !run.cancelledAt && elapsedOf(run) < (run.small ? SMALL_RUN_MS : STEP_MS * RUN_STEPS.length)) {
      run.cancelledAt = Date.now()
      run.pending = [] // 취소한 작은 실행은 고른 것을 반영하지 않는다
      saveRun(b.oa_id, run)
    }
    return { ...runOf(b), oa_id: b.oa_id, error: null }
  },
  // 올린 파일은 읽지 않는다: 첫 fixture 사건을 만든 것처럼 돌려준다.
  // 예외(발송번호 기다림 보기용): 파일 이름에 "dispatch"가 있으면 발송번호를 못 읽은 fixture(c_4)를 올린 것으로 흉내 낸다
  async createCase(file: File): Promise<CreatedCase> {
    const b = (file.name.includes('dispatch') && committed.find((x) => x.oa_result.dispatch_number.status.value !== 'confirmed')) || committed[0]
    // 같은 파일을 또 올리면 서버처럼 409 document_already_exists + 기존 사건·OA (새로고침하면 잊는다)
    const key = `${file.name}:${file.size}`
    if (uploadedKeys.has(key))
      throw new ApiError('document_already_exists', '이미 올린 통지서입니다', 409, { case_id: b.case_id, oa_id: b.oa_id })
    uploadedKeys.add(key)
    startRun(b, false)
    return { case_id: b.case_id, oa_id: b.oa_id, run_id: runOf(b).run_id }
  },
  // 다음 OA 올리기: 파일은 읽지 않고, 그 사건의 예시 OA 실행이 새로 시작한 것으로 흉내만 낸다
  async createOA(caseId: string, _file: File): Promise<CreatedOA> {
    const b = await byCase(caseId)
    startRun(b, false)
    return { oa_id: b.oa_id, run_id: runOf(b).run_id }
  },
  // 파일을 읽어 자료로 만들 수 없어서 지어내지 않고 오류로 (화면은 mock에서 이 버튼을 막아 둔다)
  async uploadDocument(_caseId: string, _file: File, _what: string): Promise<UploadedDocument> {
    throw new ApiError('not_in_mock', 'mock에서는 자료를 올릴 수 없습니다', 0)
  },
  // 출원번호 입력: 받은 번호를 사건에 남기고, 기다리던 실행은 이어서 끝난 것으로 흉내 낸다 (서버는 PATCH /cases/{id}, #70)
  async setApplicationNumber(caseId: string, applicationNumber: string): Promise<NumberEnteredOut> {
    const b = await byCase(caseId)
    if (!isApplicationNumberShape(applicationNumber))
      throw new ApiError('invalid_application_number', '출원번호 꼴이 아닙니다', 422)
    if (runOf(b).waiting_for !== 'application_number') throw new ApiError('not_waiting', '그 번호를 기다리는 실행이 없습니다', 409)
    saveAppNumber(b.case_id, applicationNumber)
    return { case_id: b.case_id, oa_id: b.oa_id, run_id: currentRunId(b) }
  },
  // 발송번호 입력: 서버처럼 꼴을 보고(422), 번호를 남기면 기다리던 같은 실행이 이어서 끝난 것으로 흉내 낸다 (PATCH /oas/{id})
  async setDispatchNumber(oaId: string, dispatchNumber: string): Promise<NumberEnteredOut> {
    const b = await byOA(oaId)
    if (!isDispatchNumberShape(dispatchNumber))
      throw new ApiError('invalid_dispatch_number', '발송번호 꼴이 아닙니다', 422)
    if (runOf(b).waiting_for !== 'dispatch_number') throw new ApiError('not_waiting', '그 번호를 기다리는 실행이 없습니다', 409)
    saveDispatchNumber(b.case_id, dispatchNumber.trim())
    return { case_id: b.case_id, oa_id: b.oa_id, run_id: currentRunId(b) }
  },
  // 정리 결과 "맞아요": 지금 보이는 정리(그 run_id)를 확인했다고 남긴다. 다시 돌려 run_id가 바뀌면 확인은 null (서버와 같게)
  async getOAResultConfirmation(oaId: string): Promise<ConfirmationOut> {
    const b = await byOA(oaId)
    const runId = gateResult(b)
    return { oa_id: b.oa_id, run_id: runId, confirmed_at: loadConfirmedAt(b.oa_id, runId) }
  },
  async confirmOAResult(oaId: string): Promise<ConfirmationOut> {
    const b = await byOA(oaId)
    const runId = gateResult(b)
    const at = new Date().toISOString()
    saveConfirmedAt(b.oa_id, runId, at)
    return { oa_id: b.oa_id, run_id: runId, confirmed_at: at }
  },
  // 다시 돌리기: 그 OA의 실행이 처음부터 새로 도는 것으로 흉내 낸다
  async rerunOA(oaId: string): Promise<CreatedRun> {
    const b = await byOA(oaId)
    startRun(b, true)
    return { run_id: runOf(b).run_id }
  },
  async getLegalChat(_chatId: string): Promise<LegalChatView> {
    throw new ApiError('not_in_mock', 'mock에는 법률 질문 대화 보기가 없습니다', 0)
  },
}

// ---- mock 실행 흉내 (D5): 통지서를 올리면 첫 fixture 사건의 실행이 새로 시작한 것으로 친다 ----
// current_step은 서버에서 자유 글 한 줄이라, 화면은 이 글을 그대로 보이기만 한다
const RUN_STEPS = [
  '통지서 읽기',
  '자료 찾아오기',
  '거절이유별 정리',
  '인용발명 대비 · 법률 근거',
  '대응 방향 후보',
]
// 작은 실행(방향 고른 뒤 초안 다시 만들기): 1초 queued, 4초까지 running, 그 뒤 succeeded (판단)
const SMALL_QUEUED_MS = 1000
const SMALL_RUN_MS = 4000
const SMALL_STEP = '초안 다시 만드는 중'
const STEP_MS = 3000 // 단계마다 약 3초 (판단)
// 결과가 "열리는" 단계 번호: 그 단계를 지나면(번호 이상이면) 결과 엔드포인트가 200
// 사건 자료 목록만 단계로 연다 (사건 단위 자료라 실행 결과 계약 밖으로 보고, 올리기 화면이 "찾아온 자료"를 실행 중에 보인다).
// 정리·대비·방향·초안 결과는 단계가 아니라 실행이 끝나야(gateResult) 열린다
const PHASE = { materials: 2, compare: 4, directions: 5 }

const MOCK_CHAT_ID = 'mock_chat_1'

// 고른 것 하나: 후보 id 또는 직접 쓴 글 중 하나만 값이 있다
interface PendingSelection {
  unitId: string
  candidateId: string | null
  written: string | null
}
// 서버 DirectionSelection과 같게: 직접 쓴 글이면 origin은 human_written, 후보면 human_selected
const selectionOf = (p: PendingSelection): DirectionSelection =>
  p.written !== null
    ? { candidate_id: null, written_direction: p.written, origin: 'human_written' }
    : { candidate_id: p.candidateId, written_direction: null, origin: 'human_selected' }

interface MockRun {
  startedAt: number
  cancelledAt?: number
  // 이 실행의 run_id (다시 돌릴 때마다 새로 만든다). 없으면 fixture 원래 run_id
  runId?: string
  // 다시 돌리기 전에 끝나 있던 실행의 run_id: 이 실행이 끝나기 전까지 결과는 그 실행 것으로 보인다
  prevRunId?: string | null
  // 방향을 고른 뒤 초안만 다시 만드는 작은 실행: 짧게 queued → running → succeeded, 단계는 한 줄
  small?: boolean
  // 작은 실행이 끝나야 GET directions에 반영되는 선택 (서버도 선택을 새 실행에 묶어 저장한다)
  pending?: PendingSelection[]
}
// mockRuns[oa_id]: 새로고침해도 이어지게 sessionStorage에 둔다 (막히면 메모리만)
const mockRuns: Record<string, MockRun> = {}
const runKey = (oaId: string) => `patent_ai:mock:v1:run:${oaId}`

function loadRun(oaId: string): MockRun | null {
  if (mockRuns[oaId]) return mockRuns[oaId]
  try {
    const raw = sessionStorage.getItem(runKey(oaId))
    if (raw) mockRuns[oaId] = JSON.parse(raw) as MockRun
  } catch (e) {
    // 저장소를 못 읽으면 메모리만 쓴다
    console.warn(`[mock] 실행 흉내 저장소를 읽지 못함 (${runKey(oaId)}): 새로고침하면 처음부터예요`, e)
  }
  return mockRuns[oaId] ?? null
}
function saveRun(oaId: string, run: MockRun) {
  mockRuns[oaId] = run
  try {
    sessionStorage.setItem(runKey(oaId), JSON.stringify(run))
  } catch (e) {
    // 저장소를 못 쓰면 메모리만 쓴다
    console.warn(`[mock] 실행 흉내 저장소에 쓰지 못함 (${runKey(oaId)}): 새로고침하면 사라져요`, e)
  }
}
// 올리기(새 사건·다음 OA)는 이전 결과가 없고, 다시 돌리기(keepPrev)는 마지막으로 끝난 실행의 결과를 이어 보인다
function startRun(b: Bundle, keepPrev: boolean, small = false) {
  flushPending(b, true) // 앞 작은 실행이 남긴 선택은 새 실행을 만들기 전에 반영한다
  const prevRunId = keepPrev ? lastDoneRunId(b) : null
  saveRun(b.oa_id, { startedAt: Date.now(), runId: `${b.run_id}_r${Date.now()}`, prevRunId, ...(small ? { small: true } : {}) })
}
// 끝난 작은 실행이 묶어 둔 선택을 방향 목록에 반영하고 저장한다 (force면 도는 중이어도)
function flushPending(b: Bundle, force = false) {
  const run = loadRun(b.oa_id)
  if (!run?.pending?.length) return
  const state = runOf(b).state
  if (!force && (state === 'queued' || state === 'running')) return
  for (const p of run.pending) {
    const unit = directions[b.oa_id]?.find((d) => d.unit_id === p.unitId)
    if (!unit) continue
    unit.selection = selectionOf(p)
    saveSelection(p.unitId, unit.selection)
    applyDraftHold(unit.unit_id, unit.selection, true)
  }
  saveRun(b.oa_id, { ...run, pending: [] })
}
const currentRunId = (b: Bundle) => loadRun(b.oa_id)?.runId ?? b.run_id
// 지금까지 결과가 확정된 마지막 실행 (없으면 null)
function lastDoneRunId(b: Bundle): string | null {
  const run = loadRun(b.oa_id)
  if (!run) return b.run_id // 시작한 적 없는 사건은 늘 끝난 상태
  const state = runOf(b).state
  if (state === 'succeeded' || state === 'waiting_for_human') return currentRunId(b)
  return run.prevRunId ?? null
}
const elapsedOf = (run: MockRun) => (run.cancelledAt ?? Date.now()) - run.startedAt

// 지금 몇 번째 단계까지 왔나: 0~4는 그 단계를 하는 중, 5는 모두 끝남. 표에 없으면 5
function phaseOf(oaId: string): number {
  const run = loadRun(oaId)
  // 작은 실행은 앞 단계를 다시 돌지 않아 앞 결과가 처음부터 다 열려 있다
  if (!run || run.small) return RUN_STEPS.length
  return Math.min(Math.floor(elapsedOf(run) / STEP_MS), RUN_STEPS.length)
}

// 사람이 넣은 출원번호 (mock만, sessionStorage). "mock 처음으로"(patent_ai:mock: 지우기)로 함께 지워진다
const appNumberKey = (caseId: string) => `patent_ai:mock:v1:appnum:${caseId}`
function loadAppNumber(caseId: string): string | null {
  try {
    return sessionStorage.getItem(appNumberKey(caseId))
  } catch {
    return null
  }
}
function saveAppNumber(caseId: string, n: string) {
  try {
    sessionStorage.setItem(appNumberKey(caseId), n)
  } catch (e) {
    console.warn(`[mock] 출원번호를 저장하지 못함 (${appNumberKey(caseId)})`, e)
  }
}
// 사람이 넣은 발송번호 (mock만, 출원번호와 같은 방식). 사건 하나에 OA 하나라 사건 번호로 둔다
const dispatchKey = (caseId: string) => `patent_ai:mock:v1:dispatch:${caseId}`
function loadDispatchNumber(caseId: string): string | null {
  try {
    return sessionStorage.getItem(dispatchKey(caseId))
  } catch {
    return null
  }
}
function saveDispatchNumber(caseId: string, n: string) {
  try {
    sessionStorage.setItem(dispatchKey(caseId), n)
  } catch (e) {
    console.warn(`[mock] 발송번호를 저장하지 못함 (${dispatchKey(caseId)})`, e)
  }
}

// 사람이 한 정리 결과 확인 (mock만, sessionStorage): OA + 그 정리 run_id마다 확인 시각. "mock 처음으로"로 지워진다
const confirmKey = (oaId: string, runId: string) => `patent_ai:mock:v1:confirm:${oaId}:${runId}`
function loadConfirmedAt(oaId: string, runId: string): string | null {
  try {
    return sessionStorage.getItem(confirmKey(oaId, runId))
  } catch {
    return null
  }
}
function saveConfirmedAt(oaId: string, runId: string, at: string) {
  try {
    sessionStorage.setItem(confirmKey(oaId, runId), at)
  } catch (e) {
    console.warn(`[mock] 정리 확인을 저장하지 못함 (${confirmKey(oaId, runId)})`, e)
  }
}
// 서버와 같게: 사람이 넣은 출원번호는 값·글자를 사람 것으로, 쪽은 비우고 "사람이 직접 입력함" 확인 글 (#70)
function withHumanNumber(b: Bundle): OAResult {
  let r = b.oa_result
  const human = (digits: string) => ({
    value: digits,
    raw_text: digits,
    page: null,
    status: { value: 'confirmed' as const, reason: null, checked: HUMAN_ENTERED_CHECKED, searched_scope: null },
    candidates: [],
  })
  const n = loadAppNumber(b.case_id)
  if (n !== null && r.application_number.status.value !== 'confirmed') r = { ...r, application_number: human(n.replace(/-/g, '')) }
  const d = loadDispatchNumber(b.case_id)
  if (d !== null && r.dispatch_number.status.value !== 'confirmed') r = { ...r, dispatch_number: human(d.replace(/-/g, '')) }
  return r
}

// 지휘(orchestrator)와 같은 규칙: 통지서에서 읽은 출원번호가 확인됨이 아니면(확인되지 않음·충돌) 사람에게 묻는다
const needsAppNumber = (b: Bundle) =>
  b.oa_result.application_number.status.value !== 'confirmed' && loadAppNumber(b.case_id) === null

// 발송번호도 같은 규칙 (출원번호를 먼저 묻고, 그다음 발송번호)
const needsDispatchNumber = (b: Bundle) =>
  b.oa_result.dispatch_number.status.value !== 'confirmed' && loadDispatchNumber(b.case_id) === null

// 실행이 끝나면: 출원번호를 모르면 출원번호 입력 기다림, 아니면 끝남 (방향 고르기는 실행을 멈추지 않는다: 확신 낮은 묶음은 선택 null로 두고 실행은 succeeded).
// mock 단순화: 출원번호를 기다리는 동안에도 뒤 단계 결과(예시)는 열어 둔다 (서버는 OA 정리까지만 있다)
function runOf(b: Bundle): RunStatusLike {
  const run = loadRun(b.oa_id)
  if (!run) return { run_id: b.run_id, state: 'succeeded', current_step: null }
  const phase = phaseOf(b.oa_id)
  const run_id = currentRunId(b)
  if (run.cancelledAt) return { run_id, state: 'cancelled', current_step: null }
  if (run.small) {
    const t = elapsedOf(run)
    if (t < SMALL_QUEUED_MS) return { run_id, state: 'queued', current_step: null }
    if (t < SMALL_RUN_MS) return { run_id, state: 'running', current_step: SMALL_STEP }
    return { run_id, state: 'succeeded', current_step: null }
  }
  if (phase < RUN_STEPS.length) return { run_id, state: 'running', current_step: RUN_STEPS[phase] }
  if (needsAppNumber(b)) return { run_id, state: 'waiting_for_human', current_step: null, waiting_for: 'application_number' }
  if (needsDispatchNumber(b)) return { run_id, state: 'waiting_for_human', current_step: null, waiting_for: 'dispatch_number' }
  // 방향 고르기는 실행을 멈추지 않는다 (확신 낮은 묶음은 선택 null + 초안 보류, 실행은 succeeded)
  return { run_id, state: 'succeeded', current_step: null }
}
// latest_run(getOA)에는 waiting_for가 없고 GET /runs/{id}에만 있다 (서버 oas.py LatestRun과 같게)
type RunStatusLike = LatestRun & { waiting_for?: string | null }
const latestOf = (r: RunStatusLike): LatestRun => ({ run_id: r.run_id, state: r.state, current_step: r.current_step })

// run_id로 사건 묶음 찾기: 다시 돌린 실행은 fixture의 run_id에 꼬리가 붙어 있다
async function byRun(runId: string): Promise<Bundle> {
  const found = (await bundles()).find((x) => x.run_id === runId || currentRunId(x) === runId)
  if (!found) throw new ApiError('run_not_found', '실행을 찾을 수 없습니다', 404)
  return found
}

// 사건 자료: 아직 안 지난 단계면 404 result_not_ready
function gate(b: Bundle, need: number) {
  if (phaseOf(b.oa_id) < need) throw new ApiError('result_not_ready', '결과가 아직 없습니다', 404)
}

// 결과 엔드포인트의 계약 (안 B): "가장 최근에 결과가 확정된 실행"의 결과만 준다. 실행 중·실패·취소된 실행의 결과는 주지 않는다.
// 판단: waiting_for_human은 출원번호·발송번호를 기다리는 실행뿐이다. 그 실행도 그때까지 확정된 결과는 열어 둔다
// (방향 고르기는 실행을 멈추지 않아 succeeded 실행의 결과로 본다).
// 돌려주는 값은 결과가 속한 실행의 run_id (다시 돌리는 중이면 이전 실행 것이라 화면의 "이전 실행 결과"가 보인다)
function gateResult(b: Bundle): string {
  const runId = lastDoneRunId(b)
  if (runId === null) throw new ApiError('result_not_ready', '결과가 아직 없습니다', 404)
  return runId
}

// mock 저장소: 예시를 복사해 두고 고른 것·고친 것을 여기에 쓴다 (예시 원본은 그대로)
const directions: Record<string, DirectionCandidates[]> = structuredClone(exampleDirections)
const drafts: Record<string, DraftsWithCheck> = structuredClone(exampleDrafts)

// ---- 사람이 고른 것·고친 것을 브라우저 localStorage에 남긴다 (D6). 화면 부품은 이 저장을 모른다 ----
// 예시 복사본 위에 "사람이 바꾼 것만" 덮는다. 서버가 오면 PUT selection · PATCH drafts 로 바뀐다.
// 저장하는 ID는 커밋된 예시(exampleDirections·exampleDrafts)의 것뿐이다. VITE_DEMO 결과에는
// 방향·초안이 없어(directions[oa] 없음) selectDirection·patchDraft가 404로 막혀 저장되지 않는다.
const STORE_PREFIX = 'patent_ai:mock:v1:'
const selectionKey = (unitId: string) => `${STORE_PREFIX}selection:${unitId}`
const draftKey = (draftId: string) => `${STORE_PREFIX}draft:${draftId}`

// 칸 값 null = "AI 원문으로 되돌림" (예시에 이미 고친 글이 있던 칸을 되돌린 경우)
interface SavedDraft {
  opinion: Record<string, string | null>
  claims: Record<string, string | null>
}

// 사생활 창 등에서는 저장소 접근이 throw한다: 조용히 넘기지 않고 알리되 화면은 메모리로 계속 돈다
function storeWrite(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch (e) {
    console.warn(`[mock] 브라우저 저장소에 쓰지 못함 (${key}): 새로고침하면 사라져요`, e)
  }
}

function saveSelection(unitId: string, selection: DirectionSelection) {
  storeWrite(selectionKey(unitId), JSON.stringify(selection))
}

// 서버처럼: 직접 쓴 방향이면 그 묶음의 초안을 AI가 만들지 않고 보류한다. 후보를 고르면 예시 초안으로 되돌린다
// (mock 단순화: 보정 청구항만 바꾼다. 서버는 그 묶음의 의견서 칸도 보류한다)
// 서버 amendment.py HELD_NO_SELECTION과 같은 글 (서버는 직접 쓴 묶음에도 이 글을 준다. 화면이 직접 쓴 묶음은 따로 안내한다)
const HELD_WRITTEN = '확신이 낮아 방향을 미리 고르지 않은 묶음입니다. 방향을 고르면 초안을 만듭니다.'
function applyDraftHold(unitId: string, selection: DirectionSelection, persist = false) {
  for (const d of Object.values(drafts)) {
    const base = Object.values(exampleDrafts).find((x) => x.draft_id === d.draft_id)
    for (const c of d.claims) {
      if (c.unit_id !== unitId) continue
      if (selection.origin === 'human_written') {
        c.ai_text = null
        c.human_text = null
        c.origin = 'ai_generated'
        c.held_reason = HELD_WRITTEN
      } else if (c.held_reason === HELD_WRITTEN) {
        const orig = base?.claims.find((x) => x.claim === c.claim)
        if (orig) Object.assign(c, structuredClone(orig))
      }
    }
    recomputeDraftOrigin(d)
    // 사람이 고친 글을 지웠거나 되돌렸으면 저장도 맞춘다 (불러오는 중에는 저장하지 않는다: 아직 덮지 않은 초안이 있다)
    if (persist) saveDraft(d)
  }
}

// 예시와 human_text가 달라진 칸(= 사람이 바꾼 칸)만 모아 저장. 하나도 없으면 키를 지운다
function saveDraft(d: DraftsWithCheck) {
  const base = Object.values(exampleDrafts).find((x) => x.draft_id === d.draft_id)
  const saved: SavedDraft = { opinion: {}, claims: {} }
  for (const sec of d.opinion) {
    const was = base?.opinion.find((x) => x.key === sec.key)?.human_text ?? null
    if (sec.human_text !== was) saved.opinion[sec.key] = sec.human_text
  }
  for (const c of d.claims) {
    const was = base?.claims.find((x) => x.claim === c.claim)?.human_text ?? null
    if (c.human_text !== was) saved.claims[String(c.claim)] = c.human_text
  }
  const empty = Object.keys(saved.opinion).length === 0 && Object.keys(saved.claims).length === 0
  storeWrite(draftKey(d.draft_id), empty ? null : JSON.stringify(saved))
}

// 칸 origin과 초안 전체 origin을 human_text로부터 다시 계산한다 (patchDraft와 불러올 때가 같은 규칙)
function recomputeDraftOrigin(d: DraftsWithCheck) {
  for (const sec of d.opinion) sec.origin = sec.human_text === null ? 'ai_generated' : 'human_edited'
  for (const c of d.claims) c.origin = c.human_text === null ? 'ai_generated' : 'human_edited'
  const edited = d.opinion.some((x) => x.origin === 'human_edited') || d.claims.some((x) => x.origin === 'human_edited')
  d.origin = edited ? 'human_edited' : 'ai_generated'
}

// 모듈을 불러올 때 한 번: 저장된 것을 예시 위에 덮는다. 덮을 곳이 없으면 그 키(또는 칸)를 지우고 알린다
function applySaved() {
  let keys: string[] = []
  try {
    keys = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i) ?? '')
  } catch (e) {
    console.warn('[mock] 브라우저 저장소를 읽지 못함: 고른 것·고친 것을 불러오지 않아요', e)
    return
  }
  const allDirections = Object.values(directions).flat()
  const allDrafts = Object.values(drafts)
  const drop = (key: string, why: string) => {
    console.warn(`[mock] 저장된 ${key} 를 지움: ${why}`)
    storeWrite(key, null)
  }
  const readJson = (key: string): unknown => {
    try {
      return JSON.parse(localStorage.getItem(key) ?? 'null')
    } catch {
      return undefined // 읽거나 해석하지 못함
    }
  }

  for (const key of keys) {
    if (key.startsWith(`${STORE_PREFIX}selection:`)) {
      const unitId = key.slice(`${STORE_PREFIX}selection:`.length)
      const saved = readJson(key) as { candidate_id?: unknown; written_direction?: unknown } | null | undefined
      const unit = allDirections.find((d) => d.unit_id === unitId)
      if (!unit) drop(key, '판단 단위가 예시에 없음')
      else if (saved && typeof saved.written_direction === 'string' && saved.written_direction.trim() !== '') {
        // 직접 쓴 글 (그 묶음 초안은 보류로 보인다)
        unit.selection = selectionOf({ unitId, candidateId: null, written: saved.written_direction })
        applyDraftHold(unitId, unit.selection)
      } else if (!saved || typeof saved.candidate_id !== 'string') drop(key, '저장된 값을 읽을 수 없음')
      else if (!unit.candidates.some((c) => c.candidate_id === saved.candidate_id)) drop(key, '후보가 예시에 없음')
      else unit.selection = selectionOf({ unitId, candidateId: saved.candidate_id, written: null })
    } else if (key.startsWith(`${STORE_PREFIX}draft:`)) {
      const draftId = key.slice(`${STORE_PREFIX}draft:`.length)
      const saved = readJson(key) as Partial<SavedDraft> | null | undefined
      const d = allDrafts.find((x) => x.draft_id === draftId)
      if (!d) drop(key, '초안이 예시에 없음')
      else if (!saved || typeof saved !== 'object') drop(key, '저장된 값을 읽을 수 없음')
      else {
        let bad = 0
        for (const [k, text] of Object.entries(saved.opinion ?? {})) {
          const sec = d.opinion.find((x) => x.key === k)
          if (sec && (typeof text === 'string' || text === null)) sec.human_text = text === sec.ai_text ? null : text
          else bad++
        }
        for (const [n, text] of Object.entries(saved.claims ?? {})) {
          const c = d.claims.find((x) => String(x.claim) === n)
          // 보류한 청구항(초안 없음)은 고칠 수 없다
          if (c && c.ai_text !== null && (typeof text === 'string' || text === null)) c.human_text = text === c.ai_text ? null : text
          else bad++
        }
        recomputeDraftOrigin(d)
        if (bad > 0) {
          console.warn(`[mock] 저장된 ${key} 에서 예시에 없는 칸 ${bad}개를 지움`)
          saveDraft(d) // 덮은 것만 다시 저장 (빈 칸이면 키 삭제)
        }
      }
    }
  }
}
// 서버 모드에서는 읽지 않는다 (api/index.ts가 오히려 지운다)
if (import.meta.env.VITE_API_MODE === 'mock') applySaved()

// patent_ai:mock: 로 시작하는 localStorage·sessionStorage 키를 모두 지운다
// ("mock 처음으로" 버튼, 그리고 서버 모드에서 옛 mock 값이 남지 않게 api/index.ts가 부른다)
export function clearMockKeys() {
  for (const store of ['localStorage', 'sessionStorage'] as const) {
    try {
      const area = window[store]
      const keys = Array.from({ length: area.length }, (_, i) => area.key(i) ?? '')
      for (const k of keys) if (k.startsWith('patent_ai:mock:')) area.removeItem(k)
    } catch (e) {
      console.warn(`[mock] ${store}를 지우지 못함`, e)
    }
  }
}

export function resetMockStorage() {
  clearMockKeys()
  window.location.reload()
}

// 지금 단계(mock 짐작): 결과가 있는 가장 뒤 단계
function stageOf(oaId: string): CaseStage {
  // 실행 중이면 아직 안 지난 단계의 결과는 없다
  const phase = phaseOf(oaId)
  if (phase < PHASE.compare) return 'summary'
  if (phase < PHASE.directions) return 'compare'
  if (drafts[oaId]) return 'drafts'
  if ((directions[oaId] ?? []).length > 0) return 'directions'
  if ((exampleUnits[oaId] ?? []).length > 0) return 'compare'
  return 'summary'
}

// unit_id가 `<oa_id>:`로 시작하는 예시만 (판단 단위 ID는 OA ID로 시작한다)
function ofOA<T>(table: Record<string, T>, oaId: string): T[] {
  return Object.entries(table)
    .filter(([unitId]) => unitId.startsWith(`${oaId}:`))
    .map(([, v]) => v)
}
