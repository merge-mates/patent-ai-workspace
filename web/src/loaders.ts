// 화면에 들어가기 전에 데이터를 받는 곳 (react-router loader). 화면 부품 안에서 따로 부르지 않는다.
import { redirect, type LoaderFunctionArgs } from 'react-router'
import { api } from './api'
import { ApiError, isNotReady } from './api/errors'
import type { ResultList } from './api/resultList'
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
import { seedRun } from './runPoll'
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
  const todos = directTodos(d)?.todos ?? []
  return { cases, extras, focus: { case: top, titles: todos.slice(0, 3).map((t) => t.title) } }
}

// /cases/:caseId → 그 사건의 가장 최근 OA 작업대로
export async function caseLoader({ params }: LoaderFunctionArgs) {
  const c = await api.getCase(params.caseId!)
  // 같은 출원번호 사건에 합쳐진 임시 사건이면 합친 사건을 연다 (#272. 옛 링크로 와도 빈 사건이 아니게)
  if (c.merged_into_case_id) return redirect(`/cases/${c.merged_into_case_id}`)
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
  // 검토할 사항 목록. 따로 받은 목록이 없으면 사건 자료 ⑥의 review_items. 그것도 None이면 null (개수와 상관없이 모름)
  reviewItems: ReviewItem[] | null
  // 원문 쪽 글자를 못 받으면 null (원문 보기에서 알린다)
  document: PageText | null
  // 대응 방향 묶음 (직접 할 일의 방향 고르기를 세려고). 결과가 아직 없으면 null (모름)
  directions: DirectionCandidates[] | null
  // 판단 단위 (직접 할 일 "묶음 N" 번호). 결과가 아직 없거나 모르면 null
  units: JudgmentUnit[] | null
  // 대비표 (단계 막대 "차이점 후보 N"을 세려고). 결과가 아직 없거나 모르면 null
  comparisons: ComparisonTable[] | null
  // 이 OA의 법률 근거 묶음 (거절이유마다 "이 거절이유의 법리"). 아직 안 찾았으면 [] (지어내지 않고 그 줄을 뺀다)
  legal: LegalEvidenceBundle[]
  // 단계마다 결과가 있는지 (D5). 404 result_not_ready였으면 false. 그 밖의 오류로 알 수 없으면 null (모름)
  ready: { summary: boolean; compare: boolean | null; directions: boolean | null; drafts: boolean | null }
  // 결과 유무만 보려던 호출이 실패했을 때 화면에 작게 보일 경고 ("<단계> 결과를 받지 못했어요")
  warnings: string[]
}

export function oaLoader({ params }: LoaderFunctionArgs): Promise<OALoaderData> {
  return loadOA(params.oaId!)
}

// /cases/new?oa=<oa_id>: 올린 뒤 같은 화면에 머문다. 주소에 oa가 없으면 올리기 전 (null).
// 새로고침해도 이어지게 이 주소로 OA·자료를 받는다
export function uploadLoader({ request }: LoaderFunctionArgs): Promise<OALoaderData | null> {
  const oaId = new URL(request.url).searchParams.get('oa')
  return oaId ? loadOA(oaId) : Promise.resolve(null)
}

// 사건 작업대에 필요한 것을 한 번에 받는다 (사건 목록의 "오늘 먼저 볼 사건"도 쓴다)
async function loadOA(oaId: string): Promise<OALoaderData> {
  const oa = await api.getOA(oaId)
  // 실행 상태 폴링에 지금 값을 넣는다 (화면은 이 값을 구독한다)
  if (oa.latest_run) seedRun(oa.latest_run)
  let draftCheckMissing = false
  const [oaResult, materialsP, reviewList, document, directionsP, legalP, unitsP, draftsP, comparisonsP] = await Promise.all([
    api.getOAResult(oa.oa_id).catch(missingAsNull),
    // 사건 자료는 없어도 화면을 막지 않는다: 아직 없음·엔드포인트 없음(not_found)은 경고 없이 null, 그 밖의 오류는 null + 경고
    probe(api.getMaterials(oa.case_id), true),
    // 목록 엔드포인트가 API v0에 없거나 아직 없을 때만 null. 다른 오류는 오류 화면으로
    api.getReviewItems(oa.case_id).catch((e: unknown) => {
      if (e instanceof ApiError && e.code === 'not_in_api_v0') return null
      return missingAsNull(e)
    }),
    // 원문 쪽 글자는 어떤 오류든 null (원문 보기에서 "받지 못함"으로 알린다)
    oa.document_id ? api.getDocument(oa.document_id).catch(() => null) : Promise.resolve(null),
    // 방향 결과가 아직 없으면 null: 0개로 보이지 않게 직접 할 일 개수는 모름
    probe(api.getDirections(oa.oa_id).then(itemsOf)),
    // 법률 근거: 결과가 아직 없으면 빈 목록
    probe(api.getLegalEvidence(oa.oa_id).then(itemsOf)),
    // 대비·초안 단계에 결과가 있는지만 알려고 부른다 (값은 쓰지 않고, 없는 것을 지어내지 않는다)
    probe(api.getUnits(oa.oa_id).then(itemsOf)),
    // 초안은 있는데 검사 결과(check)만 없으면(draft_check_missing) 초안 단계는 "있음"으로 보고 경고만 따로 단다
    probe(
      api.getDrafts(oa.oa_id).then(
        () => true,
        (e: unknown) => {
          if (e instanceof ApiError && e.code === 'draft_check_missing') {
            draftCheckMissing = true
            return true
          }
          throw e
        },
      ),
    ),
    // 단계 막대 "차이점 후보 N": 대비표를 받아 센다 (결과가 아직 없으면 null)
    probe(api.getComparisons(oa.oa_id).then(itemsOf)),
  ])
  // 결과 유무 확인이 result_not_ready 아닌 오류로 실패하면 화면 전체를 막지 않고 "모름"(null) + 경고로 둔다
  const warnings: string[] = []
  const known = <T,>(p: Probe<T>, label: string): T | null => {
    if (p.unknown) warnings.push(`${label} 결과를 받지 못했어요`)
    return p.value
  }
  const materials = known(materialsP, '사건 자료')
  // 목록 엔드포인트가 없으면(서버) ⑥의 review_items를 쓴다. None(모름)은 개수가 있어도 null로 둔다 (0건으로 그리지 않음)
  const reviewItems = reviewList ?? materials?.review_items ?? null
  const directions = known(directionsP, '대응 방향')
  const legal = known(legalP, '법률 근거') ?? []
  const units = known(unitsP, '인용발명 대비')
  const drafts = known(draftsP, '초안')
  const comparisons = known(comparisonsP, '대비표')
  if (draftCheckMissing) warnings.push('초안 검사 결과가 없어요: 누락 검사·번호 불일치를 보일 수 없어요')
  const ready = {
    summary: oaResult !== null,
    compare: unitsP.unknown ? null : units !== null,
    directions: directionsP.unknown ? null : directions !== null,
    drafts: draftsP.unknown ? null : drafts !== null,
  }
  return { oa, oaResult, materials, reviewItems, document, directions, units, comparisons, legal, ready, warnings }
}

// 결과 목록에서 목록만 (결과 유무·개수만 보는 곳)
const itemsOf = <T,>(r: ResultList<T>): T[] => r.items

// 빈 이유: 목록이 있거나 결과가 아직 없으면(null) 이유도 없다
const reasonOf = <T,>(r: ResultList<T> | null): string | null => (r && r.items.length === 0 ? r.emptyReason : null)

// 결과 유무 확인용 호출: 결과 없음(result_not_ready)은 value null, 그 밖의 오류는 unknown(모름)
interface Probe<T> {
  value: T | null
  unknown: boolean
}
// notFoundIsMissing: 서버에 엔드포인트가 아직 없어서 나는 404(not_found)도 "아직 없음"으로 본다
async function probe<T>(p: Promise<T>, notFoundIsMissing = false): Promise<Probe<T>> {
  try {
    return { value: await p, unknown: false }
  } catch (e) {
    if (isNotReady(e)) return { value: null, unknown: false }
    if (notFoundIsMissing && e instanceof ApiError && e.code === 'not_found') return { value: null, unknown: false }
    return { value: null, unknown: true }
  }
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
  // 실행이 끝났는데 목록이 빈 이유 (서버 empty_reason: 넘김·보류·확인되지 않음 등). 목록이 있거나 결과가 아직 없으면 null
  emptyReasons: { units: string | null; comparisons: string | null; clarity: string | null; legal: string | null }
}

// 3 대비와 근거: 판단 단위 · 대비표 · 명확성 문구 검토 · 법률 근거
export async function compareLoader({ params }: LoaderFunctionArgs): Promise<CompareLoaderData> {
  const oaId = params.oaId!
  // 결과가 아직 없음(result_not_ready)만 "없음"으로 받고, 다른 오류는 오류 화면으로
  const [units, comparisons, clarity, legal] = await Promise.all([
    api.getUnits(oaId).catch(notReadyAsNull),
    api.getComparisons(oaId).catch(notReadyAsNull),
    api.getClarityReviews(oaId).catch(notReadyAsNull),
    api.getLegalEvidence(oaId).catch(notReadyAsNull),
  ])
  return {
    units: units?.items ?? null,
    comparisons: comparisons?.items ?? [],
    clarity: clarity?.items ?? [],
    legal: legal?.items ?? [],
    emptyReasons: {
      units: reasonOf(units),
      comparisons: reasonOf(comparisons),
      clarity: reasonOf(clarity),
      legal: reasonOf(legal),
    },
  }
}

export interface DirectionsLoaderData {
  units: JudgmentUnit[]
  directions: DirectionCandidates[]
  // 대비표: 후보 근거의 문서 번호를 인용발명 이름(D1 등)으로 맞추려고. 아직 없으면 []
  comparisons: ComparisonTable[]
  // 아직 없으면 null (확인되지 않음으로 보인다)
  caseCheck: CaseCheck | null
  // 대응 방향 목록이 빈 이유 (서버 empty_reason). 목록이 있으면 null
  directionsEmptyReason: string | null
}

// 4 대응 방향: 묶음마다 후보 + 사건 전체 검사
// 실행 중이라 결과가 아직 없으면 null (화면은 "아직 결과가 없어요"를 보인다)
export async function directionsLoader({ params }: LoaderFunctionArgs): Promise<DirectionsLoaderData | null> {
  const oaId = params.oaId!
  const [units, directions, comparisons, caseCheck] = await Promise.all([
    api.getUnits(oaId).catch(notReadyAsNull),
    api.getDirections(oaId).catch(notReadyAsNull),
    api.getComparisons(oaId).catch(notReadyAsNull),
    api.getCaseCheck(oaId).catch(missingAsNull),
  ])
  if (units === null || directions === null) return null
  return {
    units: units.items,
    directions: directions.items,
    comparisons: comparisons?.items ?? [],
    caseCheck,
    directionsEmptyReason: reasonOf(directions),
  }
}

export interface DraftsLoaderData {
  // 초안이 아직 없으면 null (404 result_not_ready)
  drafts: DraftsWithCheck | null
  // 지금 선택: 초안이 바탕으로 삼은 선택과 다른지 본다
  directions: DirectionCandidates[]
  caseCheck: CaseCheck | null
  // 초안이 없는 이유 (서버가 result: null과 함께 준 empty_reason: 모든 묶음 보류·F4 넘김 등). 모르면 null
  draftsEmptyReason: string | null
}

// 5 의견서·보정 초안
export async function draftsLoader({ params }: LoaderFunctionArgs): Promise<DraftsLoaderData | null> {
  const oaId = params.oaId!
  let draftsEmptyReason: string | null = null
  const [drafts, directions, caseCheck] = await Promise.all([
    api.getDrafts(oaId).catch((e: unknown) => {
      // 실행이 끝났는데 초안이 없으면 서버는 200 + empty_reason을 준다 (api가 result_not_ready·httpStatus 200으로 바꿔 던짐)
      if (isNotReady(e) && e instanceof ApiError && e.httpStatus === 200) draftsEmptyReason = e.message
      return notReadyAsNull(e)
    }),
    api.getDirections(oaId).catch(notReadyAsNull),
    api.getCaseCheck(oaId).catch(missingAsNull),
  ])
  // 방향 결과가 아직 없으면(실행 중) 초안도 없다: 빈 화면 대신 "아직 결과가 없어요"
  if (directions === null) return null
  return { drafts, directions: directions.items, caseCheck, draftsEmptyReason }
}
