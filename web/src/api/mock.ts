// mock 모드 (VITE_API_MODE=mock): 서버 없이 fixture를 돌려준다.
// fixture는 scripts/web_fixtures.py가 가짜 통지서 + 기록된 모델 응답으로 만든 것 (git에 있음).
// 시연용 실제 결과(web/.demo/*.json, git 밖)는 VITE_DEMO=1일 때만 더 읽는다.
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
  UploadedDocument,
} from '../types/provisional/case'
import type { ClarityReview } from '../types/generated/ClarityReview'
import type { ComparisonTable } from '../types/generated/ComparisonTable'
import type { DirectionCandidates } from '../types/generated/DirectionCandidates'
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
import { ApiError } from './errors'

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
    last_opened_at: b.last_opened_at,
  }
}

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
      latest_run: runOf(b),
    }
  },
  async getOAResult(oaId: string): Promise<OAResultResponse> {
    const b = await byOA(oaId)
    gate(b, PHASE.summary)
    return { oa_id: b.oa_id, run_id: b.run_id, status: b.oa_result.status.value, result: b.oa_result }
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
    gate(b, PHASE.summary)
    if (!b.review_items) throw new ApiError('result_not_ready', '검토할 사항 목록이 아직 없습니다', 404)
    return b.review_items
  },
  // 사건 목록에 더 보이는 값 (fixture·예시에서 채운다). 서버 모드는 비어 있어 "모름"
  async listCaseExtras(): Promise<CaseListExtra[]> {
    return (await bundles()).map((b) => {
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
  async getUnits(oaId: string): Promise<JudgmentUnit[]> {
    gate(await byOA(oaId), PHASE.compare)
    return exampleUnits[oaId] ?? []
  },
  async getComparisons(oaId: string): Promise<ComparisonTable[]> {
    gate(await byOA(oaId), PHASE.compare)
    return ofOA(exampleComparisons, oaId)
  },
  async getClarityReviews(oaId: string): Promise<ClarityReview[]> {
    gate(await byOA(oaId), PHASE.compare)
    return ofOA(exampleClarity, oaId)
  },
  async getLegalEvidence(oaId: string): Promise<LegalEvidenceBundle[]> {
    gate(await byOA(oaId), PHASE.compare)
    return ofOA(exampleLegal, oaId)
  },
  // 이어 묻기: mock은 대화를 기억하지 않고 고정 chat_id만 돌려준다 (서버 모양만 맞춤)
  async askLegal(q: LegalQuestion, chatId?: string): Promise<LegalAnswer> {
    return { chat_id: chatId ?? MOCK_CHAT_ID, answer: exampleLegalAnswer(q) }
  },
  // ⑤ 대응 방향·초안: 사람이 고른 것·고친 것은 메모리 + localStorage에 남는다 (아래 저장 코드, "mock 처음으로"로 지움)
  async getDirections(oaId: string): Promise<DirectionCandidates[]> {
    gate(await byOA(oaId), PHASE.directions)
    return directions[oaId] ?? []
  },
  async selectDirection(unitId: string, candidateId: string): Promise<DirectionCandidates> {
    const list = Object.values(directions).flat()
    const found = list.find((d) => d.unit_id === unitId)
    if (!found) throw new ApiError('unit_not_found', '판단 단위를 찾을 수 없습니다', 404)
    if (!found.candidates.some((c) => c.candidate_id === candidateId))
      throw new ApiError('candidate_not_found', '후보를 찾을 수 없습니다', 400)
    // PUT으로 저장한 선택은 1등과 같아도 "사람이 고름" (docs/api/README.md)
    found.selection = { candidate_id: candidateId, origin: 'human_selected' }
    saveSelection(unitId, candidateId)
    // 사람 선택은 selection.origin 한 곳에만 둔다 (묶음 맨 위 origin은 ai_generated 그대로)
    return found
  },
  async getCaseCheck(oaId: string): Promise<CaseCheck> {
    gate(await byOA(oaId), PHASE.directions)
    // 예시가 없으면 "다루지 않은 거절이유 없음"처럼 지어내지 않고 결과 없음으로
    const check = exampleCaseChecks[oaId]
    if (!check) throw new ApiError('result_not_ready', '사건 전체 검사 결과가 아직 없습니다', 404)
    return check
  },
  async getDrafts(oaId: string): Promise<DraftsWithCheck> {
    gate(await byOA(oaId), PHASE.directions)
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
    const b = (await bundles()).find((x) => x.run_id === runId)
    if (!b) throw new ApiError('run_not_found', '실행을 찾을 수 없습니다', 404)
    return { ...runOf(b), oa_id: b.oa_id, error: null }
  },
  async cancelRun(runId: string): Promise<RunStatus> {
    const b = (await bundles()).find((x) => x.run_id === runId)
    if (!b) throw new ApiError('run_not_found', '실행을 찾을 수 없습니다', 404)
    const run = loadRun(b.oa_id)
    // 이미 끝난 실행은 취소할 수 없다 (끝난 것을 취소로 바꾸지 않는다)
    if (run && !run.cancelledAt && elapsedOf(run) < STEP_MS * RUN_STEPS.length) {
      run.cancelledAt = Date.now()
      saveRun(b.oa_id, run)
    }
    return { ...runOf(b), oa_id: b.oa_id, error: null }
  },
  // 올린 파일은 읽지 않는다: 첫 fixture 사건을 만든 것처럼 돌려준다
  async createCase(_file: File): Promise<CreatedCase> {
    const b = committed[0]
    startRun(b.oa_id)
    return { case_id: b.case_id, oa_id: b.oa_id, run_id: b.run_id }
  },
  // 다음 OA 올리기: 파일은 읽지 않고, 그 사건의 예시 OA 실행이 새로 시작한 것으로 흉내만 낸다
  async createOA(caseId: string, _file: File): Promise<CreatedOA> {
    const b = await byCase(caseId)
    startRun(b.oa_id)
    return { oa_id: b.oa_id, run_id: b.run_id }
  },
  // 파일을 읽어 자료로 만들 수 없어서 지어내지 않고 오류로 (화면은 mock에서 이 버튼을 막아 둔다)
  async uploadDocument(_caseId: string, _file: File): Promise<UploadedDocument> {
    throw new ApiError('not_in_mock', 'mock에서는 자료를 올릴 수 없습니다', 0)
  },
  // 다시 돌리기: 그 OA의 실행이 처음부터 새로 도는 것으로 흉내 낸다
  async rerunOA(oaId: string): Promise<CreatedRun> {
    const b = await byOA(oaId)
    startRun(b.oa_id)
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
const STEP_MS = 3000 // 단계마다 약 3초 (판단)
// 결과가 "열리는" 단계 번호: 그 단계를 지나면(번호 이상이면) 결과 엔드포인트가 200
const PHASE = { materials: 2, summary: 3, compare: 4, directions: 5 }

const MOCK_CHAT_ID = 'mock_chat_1'

interface MockRun {
  startedAt: number
  cancelledAt?: number
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
function startRun(oaId: string) {
  saveRun(oaId, { startedAt: Date.now() })
}
const elapsedOf = (run: MockRun) => (run.cancelledAt ?? Date.now()) - run.startedAt

// 지금 몇 번째 단계까지 왔나: 0~4는 그 단계를 하는 중, 5는 모두 끝남. 표에 없으면 5
function phaseOf(oaId: string): number {
  const run = loadRun(oaId)
  if (!run) return RUN_STEPS.length
  return Math.min(Math.floor(elapsedOf(run) / STEP_MS), RUN_STEPS.length)
}

// 실행이 끝나면: 확신 낮은 묶음이 아직 안 골라졌으면 사람 기다림, 아니면 끝남
function runOf(b: Bundle): LatestRun {
  const run = loadRun(b.oa_id)
  if (!run) return { run_id: b.run_id, state: 'succeeded', current_step: null }
  const phase = phaseOf(b.oa_id)
  if (run.cancelledAt) return { run_id: b.run_id, state: 'cancelled', current_step: null }
  if (phase < RUN_STEPS.length) return { run_id: b.run_id, state: 'running', current_step: RUN_STEPS[phase] }
  const waiting = (directions[b.oa_id] ?? []).some(
    (d) => d.flags.includes('needs_human_judgment') && d.selection === null,
  )
  return { run_id: b.run_id, state: waiting ? 'waiting_for_human' : 'succeeded', current_step: null }
}

// 아직 안 지난 단계의 결과는 404 result_not_ready (서버와 같게)
function gate(b: Bundle, need: number) {
  if (phaseOf(b.oa_id) < need) throw new ApiError('result_not_ready', '결과가 아직 없습니다', 404)
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

function saveSelection(unitId: string, candidateId: string) {
  storeWrite(selectionKey(unitId), JSON.stringify({ candidate_id: candidateId, origin: 'human_selected' }))
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
      const saved = readJson(key) as { candidate_id?: unknown } | null | undefined
      const unit = allDirections.find((d) => d.unit_id === unitId)
      if (!unit) drop(key, '판단 단위가 예시에 없음')
      else if (!saved || typeof saved.candidate_id !== 'string') drop(key, '저장된 값을 읽을 수 없음')
      else if (!unit.candidates.some((c) => c.candidate_id === saved.candidate_id)) drop(key, '후보가 예시에 없음')
      else unit.selection = { candidate_id: saved.candidate_id, origin: 'human_selected' }
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
