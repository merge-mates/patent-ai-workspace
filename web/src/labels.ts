// 서버가 주는 영어 코드 → 화면에 보이는 한국어 (docs/api/README.md 2절: 화면에서 한국어로 보여 준다)
import type { LookupResult } from './types/generated/CaseMaterials'
import type { NoticeKind, RejectionKind, UnverifiedReason } from './types/generated/OAResult'
import type { AddedSource, AmendmentKind, AmendmentLimit, Confidence, RebuttalType } from './types/generated/DirectionCandidates'
import type { FurtherReviewWhy, LegalSourceKind, ReviewVerdict, Speaker } from './types/generated/LegalEvidenceBundle'
import type { RunState } from './types/provisional/case'

export const unverifiedReasonLabel: Record<UnverifiedReason, string> = {
  not_extracted: '못 뽑음',
  ambiguous: '애매',
  lookup_failed: '조회 실패',
  body_missing: '본문 미확보',
  evidence_rejected: '근거 빠짐',
  limit_reached: '상한 도달',
  edition_unknown: '판본 미확인',
  input_unverified: '앞 단계 미확인',
}

export const noticeKindLabel: Record<NoticeKind, string> = {
  initial: '최초거절이유통지',
  final: '최후거절이유통지',
  unknown: '통지 종류 모름',
}

export const rejectionKindLabel: Record<RejectionKind, string> = {
  novelty: '신규성',
  inventive_step: '진보성',
  clarity: '명확성',
  other: '그 밖',
}

// 조문 코드(`29-2`, `42-4-2`, 여럿이면 `29-1-1|29-1-2`) → 특허법 조문 글자
export function articleLabel(code: string | null): string {
  if (!code) return '조문 모름'
  return code
    .split('|')
    .map((part) => {
      const [jo, hang, ho] = part.split('-')
      return `제${jo}조${hang ? `제${hang}항` : ''}${ho ? `제${ho}호` : ''}`
    })
    .join(', ')
}

export const runStateLabel: Record<RunState, string> = {
  queued: '대기',
  running: '실행 중',
  waiting_for_human: '사람 기다림',
  succeeded: '끝남',
  failed: '실패',
  cancelled: '취소',
}

export const lookupResultLabel: Record<LookupResult, string> = {
  lookup_failed: '조회 실패',
  body_missing: '본문 미확보',
  unsupported_country: '지원 안 하는 나라',
}

export const materialKindLabel: Record<string, string> = {
  oa: '의견제출통지서',
  amendment: '보정서',
  opinion: '의견서',
  claims: '청구항',
  spec: '명세서',
  citation: '인용문헌',
}

export const sourceLabel: Record<string, string> = {
  uploaded: '올림',
  api: '자동 조회',
}

export const sourceKindLabel: Record<LegalSourceKind, string> = {
  statute: '법령',
  guideline: '심사기준',
  precedent: '판례',
  trial: '심결',
}

// ④ 근거 화자·검토 판정·더 볼 이유·질문 출처
export const speakerLabel: Record<Speaker, string> = {
  court: '법원 판단',
  party: '당사자 주장',
  unknown: '화자 불명',
}

export const reviewVerdictLabel: Record<ReviewVerdict, string> = {
  supported: '뒷받침됨',
  partial: '일부만 뒷받침',
  not_supported: '뒷받침 못 함',
  undetermined: '판정 못 함',
}

export const furtherReviewWhyLabel: Record<FurtherReviewWhy, string> = {
  opposite_holding: '반대 취지',
  edition_unknown: '판본 모름',
  other_edition: '다른 판본',
  edition_out_of_scope: '기준일 밖 판본',
  not_used_candidate: '쓰지 않은 후보',
}

// ⑤ 대응 방향: 보정 종류·부가한 구성의 출처·보정 제한·반박 유형
export const amendmentKindLabel: Record<AmendmentKind, string> = {
  unchanged: '그대로',
  limit: '한정',
  add: '부가',
  delete: '삭제',
  correct_error: '오기 정정',
  clarify: '명확화',
}

export const addedSourceLabel: Record<AddedSource, string> = {
  other_dependent: '다른 종속항',
  spec: '발명의 설명',
  other: '기타',
}

export const amendmentLimitLabel: Record<AmendmentLimit, string> = {
  initial: '최초',
  final: '최후',
}

export const rebuttalTypeLabel: Record<RebuttalType, string> = {
  difference: '차이점',
  no_motivation: '결합 동기 없음',
  combination_difficulty: '결합 곤란',
  remarkable_effect: '현저한 효과',
  hindsight: '사후적 고찰',
  not_substantially_same: '실질적 동일 아님',
  grace_period: '공지예외',
  obvious_error: '명백한 오기',
  clear_from_description: '설명으로 명확',
  other: '그 밖',
}

// 확신도 3단계 (% 숫자를 쓰지 않는다)
export const confidenceLabel: Record<Confidence, string> = { high: '높음', medium: '중간', low: '낮음' }
