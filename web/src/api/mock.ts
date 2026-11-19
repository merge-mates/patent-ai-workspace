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
  // 올린 파일은 읽지 않는다: 첫 fixture 사건을 만든 것처럼 돌려준다
  async createCase(_file: File): Promise<CreatedCase> {
    const b = committed[0]
    return { case_id: b.case_id, oa_id: b.oa_id, run_id: b.run_id }
  },
}
