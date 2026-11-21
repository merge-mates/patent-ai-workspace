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
  OADetail,
  OAResultResponse,
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
    run_state: 'succeeded',
    status: r.status.value,
    review_items_count: b.review_items?.length ?? null,
    updated_at: b.last_opened_at,
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
      latest_run: { run_id: b.run_id, state: 'succeeded', current_step: null },
    }
  },
  async getOAResult(oaId: string): Promise<OAResultResponse> {
    const b = await byOA(oaId)
    return { oa_id: b.oa_id, run_id: b.run_id, status: b.oa_result.status.value, result: b.oa_result }
  },
  async getMaterials(caseId: string): Promise<CaseMaterials> {
    const m = (await byCase(caseId)).materials
    if (!m) throw new ApiError('result_not_ready', '사건 자료 목록이 아직 없습니다', 404)
    return m
  },
  async getReviewItems(caseId: string): Promise<ReviewItem[]> {
    const items = (await byCase(caseId)).review_items
    if (!items) throw new ApiError('result_not_ready', '검토할 사항 목록이 아직 없습니다', 404)
    return items
  },
  async getDocument(documentId: string): Promise<PageText> {
    const found = (await bundles()).find((b) => b.document?.document_id === documentId)
    if (!found?.document) throw new ApiError('document_not_found', '원문을 찾을 수 없습니다', 404)
    return found.document
  },
  // ②③④는 스키마가 아직 없어 예시 데이터 (types/provisional/examples.ts)
  async getUnits(oaId: string): Promise<JudgmentUnit[]> {
    await byOA(oaId)
    return exampleUnits[oaId] ?? []
  },
  async getComparisons(oaId: string): Promise<ComparisonTable[]> {
    return ofOA(exampleComparisons, oaId)
  },
  async getClarityReviews(oaId: string): Promise<ClarityReview[]> {
    return ofOA(exampleClarity, oaId)
  },
  async getLegalEvidence(oaId: string): Promise<LegalEvidenceBundle[]> {
    return ofOA(exampleLegal, oaId)
  },
  async askLegal(q: LegalQuestion): Promise<LegalEvidenceBundle> {
    return exampleLegalAnswer(q)
  },
  // ⑤ 대응 방향·초안: 사람이 고른 것·고친 것은 이 탭 메모리에만 둔다 (새로고침하면 처음으로)
  async getDirections(oaId: string): Promise<DirectionCandidates[]> {
    await byOA(oaId)
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
    // 사람 선택은 selection.origin 한 곳에만 둔다 (묶음 맨 위 origin은 ai_generated 그대로)
    return found
  },
  async getCaseCheck(oaId: string): Promise<CaseCheck> {
    await byOA(oaId)
    // 예시가 없으면 "다루지 않은 거절이유 없음"처럼 지어내지 않고 결과 없음으로
    const check = exampleCaseChecks[oaId]
    if (!check) throw new ApiError('result_not_ready', '사건 전체 검사 결과가 아직 없습니다', 404)
    return check
  },
  async getDrafts(oaId: string): Promise<DraftsWithCheck> {
    await byOA(oaId)
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
    const edited = d.opinion.some((x) => x.origin === 'human_edited') || d.claims.some((x) => x.origin === 'human_edited')
    d.origin = edited ? 'human_edited' : 'ai_generated'
    return { ...d }
  },
  // 올린 파일은 읽지 않는다: 첫 fixture 사건을 만든 것처럼 돌려준다
  async createCase(_file: File): Promise<CreatedCase> {
    const b = committed[0]
    return { case_id: b.case_id, oa_id: b.oa_id, run_id: b.run_id }
  },
}

// mock 저장소: 예시를 복사해 두고 고른 것·고친 것을 여기에 쓴다 (예시 원본은 그대로)
const directions: Record<string, DirectionCandidates[]> = structuredClone(exampleDirections)
const drafts: Record<string, DraftsWithCheck> = structuredClone(exampleDrafts)

// unit_id가 `<oa_id>:`로 시작하는 예시만 (판단 단위 ID는 OA ID로 시작한다)
function ofOA<T>(table: Record<string, T>, oaId: string): T[] {
  return Object.entries(table)
    .filter(([unitId]) => unitId.startsWith(`${oaId}:`))
    .map(([, v]) => v)
}
