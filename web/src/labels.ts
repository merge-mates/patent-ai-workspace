// 서버가 주는 영어 코드 → 화면에 보이는 한국어 (docs/api/README.md 2절: 화면에서 한국어로 보여 준다)
import type { LookupResult } from './types/generated/CaseMaterials'
import type { NoticeKind, RejectionKind, UnverifiedReason } from './types/generated/OAResult'
import type { RunState } from './types/provisional/case'

export const unverifiedReasonLabel: Record<UnverifiedReason, string> = {
  not_extracted: '못 뽑음',
  ambiguous: '애매',
  lookup_failed: '조회 실패',
  body_missing: '본문 미확보',
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
