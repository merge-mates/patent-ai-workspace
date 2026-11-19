// 예시 데이터: ② 판단 단위 · ③ 대비표 · 명확성 문구 검토 · ④ 법률 근거.
// F2~F4 설계 뒤 뽑은 타입으로 바꿈 (그때 fixture도 core에서 만든다). 화면 모양을 보려는 가짜 값이다.
// 판례·심결 번호는 실제 사건이 아니라 "예시"로 적는다 (실제 근거처럼 읽히지 않게).
import type { Status, UnverifiedReason } from '../generated/OAResult'
import type {
  ClarityReview,
  ComparisonTable,
  JudgmentUnit,
  LegalEvidenceBundle,
  LegalQuestion,
  ResultCommon,
} from './analysis'

// 상태 만들기 (예시 데이터를 짧게 쓰려고)
const ok = (checked: string): Status => ({ value: 'confirmed', reason: null, checked, searched_scope: null })
const unv = (reason: UnverifiedReason): Status => ({ value: 'unverified', reason, checked: null, searched_scope: null })
const none = (scope: string): Status => ({ value: 'not_found_in_scope', reason: null, checked: null, searched_scope: scope })
const common = (status: Status): ResultCommon => ({
  status, evidence: [], origin: 'ai_generated', needs_recheck: false, recheck_reason: null, flags: [],
})

// 상태 모으기: 가장 나쁜 값 (충돌 > 확인되지 않음 > 조회 범위 내 없음 > 확인됨, data-model 3절)
const WORST: Status['value'][] = ['conflict', 'unverified', 'not_found_in_scope', 'confirmed']
const worst = (xs: Status[], checked: string): Status => {
  for (const v of WORST) {
    const found = xs.find((s) => s.value === v)
    if (found) return v === 'confirmed' ? ok(checked) : found
  }
  return unv('not_extracted') // 모을 것이 없으면 확인되지 않음
}

// ---- ② 판단 단위 ----
export const exampleUnits: Record<string, JudgmentUnit[]> = {
  oa_1: [
    { unit_id: 'oa_1:29-1-1:c1', rejection: 1, rejection_kind: 'novelty', unit_kind: 'independent_group', representative_claim: 1, claims: [1], read_with: [], order: 1, parent_unit_id: null, ...common(unv('ambiguous')) },
    { unit_id: 'oa_1:29-2:c1', rejection: 2, rejection_kind: 'inventive_step', unit_kind: 'independent_group', representative_claim: 1, claims: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13], read_with: [], order: 2, parent_unit_id: null, ...common(unv('body_missing')) },
    { unit_id: 'oa_1:42-4-2:c6', rejection: 3, rejection_kind: 'clarity', unit_kind: 'single_claim', representative_claim: 6, claims: [6], read_with: [1, 5], order: 3, parent_unit_id: null, ...common(ok('명세서 정의 대조')) },
    { unit_id: 'oa_1:42-4-2:c7', rejection: 3, rejection_kind: 'clarity', unit_kind: 'single_claim', representative_claim: 7, claims: [7], read_with: [1], order: 4, parent_unit_id: null, ...common(none('최초 명세서 전체')) },
  ],
  oa_2: [
    { unit_id: 'oa_2:29-2:c1', rejection: 1, rejection_kind: 'inventive_step', unit_kind: 'independent_group', representative_claim: 1, claims: [1, 2, 3, 4], read_with: [], order: 1, parent_unit_id: null, ...common(ok('인용 위치 대조')) },
  ],
  oa_3: [
    { unit_id: 'oa_3:29-2:c1', rejection: 1, rejection_kind: 'inventive_step', unit_kind: 'independent_group', representative_claim: 1, claims: [1, 2, 3, 4], read_with: [], order: 1, parent_unit_id: null, ...common(unv('body_missing')) },
    { unit_id: 'oa_3:42-4-2:c1', rejection: 2, rejection_kind: 'clarity', unit_kind: 'single_claim', representative_claim: 1, claims: [1], read_with: [], order: 2, parent_unit_id: null, ...common(ok('명세서 정의 대조')) },
  ],
}

// ---- ③ 대비표 ----
export const exampleComparisons: Record<string, ComparisonTable> = {
  'oa_1:29-1-1:c1': {
    unit_id: 'oa_1:29-1-1:c1',
    rejection_kind: 'novelty',
    citations: [{ label: 'D1', number: 'KR20990000011A', compared: true, skipped_reason: null, skipped_status: null }],
    rows: [
      { element: '영상을 촬영하는 카메라 모듈', element_location: '청구항 1 [구성 1-1]', citation: 'D1', location: '[0014]', judgment: 'disclosed', paragraph_source: 'examiner', why_retrieved: null, status: ok('D1 [0014] 대조') },
      { element: '촬영 영상에서 프리뷰 이미지를 만드는 처리부', element_location: '청구항 1 [구성 1-2]', citation: 'D1', location: '[0056]', judgment: 'disclosed', paragraph_source: 'examiner', why_retrieved: null, status: ok('D1 [0056] 대조') },
      { element: '프리뷰 이미지를 폐곡선으로 나누는 분할부', element_location: '청구항 1 [구성 1-3]', citation: 'D1', location: '도 4b', judgment: 'unclear', paragraph_source: 'examiner', why_retrieved: null, status: unv('ambiguous') },
    ],
    summary: { kind: 'novelty', citation: 'D1', verdict: 'substantially_same_candidate', reason: '구성 1-1·1-2는 D1에 그대로 있고, 1-3은 도 4b의 영역 표시가 폐곡선 분할인지 그림만으로 애매함' },
    ...common(unv('ambiguous')),
  },
  'oa_1:29-2:c1': {
    unit_id: 'oa_1:29-2:c1',
    rejection_kind: 'inventive_step',
    citations: [
      { label: 'D1', number: 'KR20990000011A', compared: true, skipped_reason: null, skipped_status: null },
      { label: 'D2', number: 'KR20990000012A', compared: false, skipped_reason: '본문 조회 실패 · 올려 주면 대비', skipped_status: unv('lookup_failed') },
    ],
    rows: [
      { element: '영상을 촬영하는 카메라 모듈', element_location: '청구항 1 [구성 1-1]', citation: 'D1', location: '[0020]', judgment: 'disclosed', paragraph_source: 'examiner', why_retrieved: null, status: ok('D1 [0020] 대조') },
      { element: '촬영 영상에서 프리뷰 이미지를 만드는 처리부', element_location: '청구항 1 [구성 1-2]', citation: 'D1', location: '[0069]', judgment: 'disclosed', paragraph_source: 'examiner', why_retrieved: null, status: ok('D1 [0069] 대조') },
      { element: '프리뷰 이미지를 폐곡선으로 나누는 분할부', element_location: '청구항 1 [구성 1-3]', citation: 'D1', location: '[0071]', judgment: 'difference_candidate', paragraph_source: 'ai_found', why_retrieved: "청구항의 '폐곡선으로 나눔'과 같은 뜻의 '영역을 둘러 나눈다'가 있는 문단 (문단 검색 1위)", status: ok('D1 [0071] 대조') },
      { element: '프리뷰 이미지를 폐곡선으로 나누는 분할부', element_location: '청구항 1 [구성 1-3]', citation: 'D2', location: '[0043]', judgment: 'unclear', paragraph_source: 'examiner', why_retrieved: null, status: unv('body_missing') },
      { element: '나눈 영역마다 노출을 따로 정하는 제어부', element_location: '청구항 1 [구성 1-4]', citation: 'D1', location: null, judgment: 'difference_candidate', paragraph_source: 'ai_found', why_retrieved: "'노출'·'영역별' 문단을 찾았으나 영역별로 따로 정한다는 글은 없음", status: none('D1 본문 전체') },
    ],
    summary: {
      kind: 'inventive_step',
      differences: ['D1은 프리뷰 이미지를 폐곡선으로 나누지 않고 사각 격자로 나눔 (구성 1-3)', '나눈 영역마다 노출을 따로 정하는 글이 D1에 없음 (구성 1-4)'],
      combination: '심사관은 D2의 폐곡선 분할을 D1에 결합. D2 본문을 받지 못해 결합 동기 문단은 확인되지 않음',
      effect_candidates: ['영역별 노출 조정으로 역광 장면의 프리뷰가 바로 보인다는 효과 (명세서 [0088])'],
    },
    ...common(unv('body_missing')),
  },
  'oa_2:29-2:c1': {
    unit_id: 'oa_2:29-2:c1',
    rejection_kind: 'inventive_step',
    citations: [
      { label: 'D1', number: 'KR20990000001A', compared: true, skipped_reason: null, skipped_status: null },
      { label: 'D2', number: 'JP2099000001A', compared: false, skipped_reason: '지원 안 하는 나라 (JP) · 직접 확인', skipped_status: null },
    ],
    rows: [
      { element: '온도를 재는 센서부', element_location: '청구항 1 [구성 1-1]', citation: 'D1', location: '[0023]', judgment: 'disclosed', paragraph_source: 'examiner', why_retrieved: null, status: ok('D1 [0023] 대조') },
      { element: '센서 값을 보정하는 보정부', element_location: '청구항 1 [구성 1-2]', citation: 'D1', location: '[0031]', judgment: 'difference_candidate', paragraph_source: 'examiner', why_retrieved: null, status: ok('D1 [0031] 대조') },
    ],
    summary: {
      kind: 'inventive_step',
      differences: ['D1의 보정은 고정 상수이고 청구항은 주변 온도에 따라 바꿈 (구성 1-2)'],
      combination: 'D2(JP)와의 결합은 지원 안 하는 나라라 대비하지 않음 · 직접 확인',
      effect_candidates: ['주변 온도가 바뀌어도 측정 오차가 줄어든다는 효과 (명세서 [0040])'],
    },
    ...common(ok('인용 위치 대조')),
  },
  'oa_3:29-2:c1': {
    unit_id: 'oa_3:29-2:c1',
    rejection_kind: 'inventive_step',
    citations: [
      { label: 'D1', number: 'KR20990000003A', compared: false, skipped_reason: '본문 미확보 · 올려 주면 대비', skipped_status: unv('body_missing') },
      { label: 'D2', number: 'US20990000001A1', compared: false, skipped_reason: '본문 조회 실패 · 올려 주면 대비', skipped_status: unv('lookup_failed') },
    ],
    rows: [],
    summary: { kind: 'inventive_step', differences: [], combination: '인용문헌 본문을 받지 못해 대비를 보류함', effect_candidates: [] },
    ...common(unv('body_missing')),
  },
}

// ---- 명확성 문구 검토 ----
export const exampleClarity: Record<string, ClarityReview> = {
  'oa_1:42-4-2:c6': {
    unit_id: 'oa_1:42-4-2:c6', claim: 6, term: '상기 프리뷰 이미지', claim_location: '청구항 6 둘째 줄',
    spec_definition: { text: '프리뷰 이미지란 촬영 전에 화면에 보이는 축소 영상을 말한다.', location: '최초 명세서 [0031]' },
    note: "청구항 6은 청구항 5를 인용하는데 청구항 5에는 '프리뷰 이미지'가 없음 (청구항 1에 있음). 인용 관계 확인 필요",
    ...common(ok('명세서 [0031] 대조')),
  },
  'oa_1:42-4-2:c7': {
    unit_id: 'oa_1:42-4-2:c7', claim: 7, term: '모듈들', claim_location: '청구항 7 첫째 줄',
    spec_definition: null,
    note: '어떤 모듈을 가리키는지 명세서에서 정의를 찾지 못함',
    ...common(none('최초 명세서 전체 · 청구범위')),
  },
  'oa_3:42-4-2:c1': {
    unit_id: 'oa_3:42-4-2:c1', claim: 1, term: '약', claim_location: '청구항 1 셋째 줄',
    spec_definition: { text: '온도 범위는 설정값의 ±5% 안을 말한다.', location: '최초 명세서 [0019]' },
    note: "'약'의 범위를 명세서 [0019]가 정함. 청구항에 수치로 옮길지 검토",
    ...common(ok('명세서 [0019] 대조')),
  },
}

// ---- ④ 법률 근거 (OA 흐름에서 지휘가 자동으로 찾은 것, 판단 단위마다) ----
const CHECKED_ON = '2026-11-18'

export const exampleLegal: Record<string, LegalEvidenceBundle> = {
  'oa_1:29-1-1:c1': {
    bundle_id: 'le_1', unit_id: 'oa_1:29-1-1:c1', question: '신규성: 청구항과 인용발명이 실질적으로 같은지 판단하는 기준', as_of: null, checked_on: CHECKED_ON,
    claims: [
      {
        no: 1, text: '신규성은 청구항 발명과 인용발명의 구성이 같은지, 차이가 있어도 실질적으로 같은지로 판단한다.', status: ok('심사기준 원문 대조'),
        sources: [
          { source_kind: 'exam_guideline', identifier: '특허·실용신안 심사기준 제3부 제2장 (예시 위치)', edition: '2099.1. 개정 (예시)', location: '4.3 실질적 동일', text_kind: 'full', speaker: null, excerpt: '차이가 주지 관용기술의 단순한 부가·전환 정도이면 실질적으로 같다고 본다.', status: ok('원문 대조') },
          { source_kind: 'precedent', identifier: '대법원 예시판결 20XX후0001', edition: null, location: '판결 이유 2.가.', text_kind: 'full', speaker: 'court', excerpt: '두 발명의 차이가 과제 해결을 위한 구체적 수단에서 미세한 차이에 불과하면 실질적으로 동일하다.', status: ok('판례 전문 대조') },
        ],
      },
    ],
    further_review: ['도 4b의 영역 표시가 폐곡선인지 원문 도면 확인', '실질적 동일을 부정한 판례가 더 있는지'],
    ...common(ok('주장마다 근거 원문 대조')),
  },
  'oa_1:29-2:c1': {
    bundle_id: 'le_2', unit_id: 'oa_1:29-2:c1', question: '진보성: 차이점 확정 뒤 결합 동기와 효과를 보는 기준', as_of: null, checked_on: CHECKED_ON,
    claims: [
      {
        no: 1, text: '진보성은 청구항과 가장 가까운 인용발명의 차이점을 먼저 확정하고, 통상의 기술자가 그 차이를 쉽게 극복할 수 있는지로 본다.', status: unv('edition_unknown'), // 근거 중 조문 판본을 모름
        sources: [
          { source_kind: 'statute', identifier: '특허법 제29조제2항', edition: null, location: '제29조제2항', text_kind: 'full', speaker: null, excerpt: '(예시 요약) 통상의 지식을 가진 사람이 인용발명으로 쉽게 발명할 수 있으면 특허를 받을 수 없다.', status: unv('edition_unknown') },
          { source_kind: 'exam_guideline', identifier: '특허·실용신안 심사기준 제3부 제3장 (예시 위치)', edition: '2099.1. 개정 (예시)', location: '5.1 판단 순서', text_kind: 'full', speaker: null, excerpt: '청구항 발명과 가장 가까운 인용발명을 고르고 차이점을 확정한 뒤…', status: ok('원문 대조') },
        ],
      },
      {
        no: 2, text: '인용발명을 결합하려면 결합할 동기나 암시가 인용발명이나 기술상식에 있어야 한다.', status: none('특허심판원 심결 요지 2015~2025 · "폐곡선 분할" 결합'), // 근거 하나가 조회 범위 내 없음
        sources: [
          { source_kind: 'precedent', identifier: '대법원 예시판결 20XX후0002', edition: null, location: '판결 이유 3.', text_kind: 'full', speaker: 'court', excerpt: '사후적 고찰로 결합을 쉽다고 보아서는 안 된다.', status: ok('판례 전문 대조') },
          { source_kind: 'trial_decision', identifier: '특허심판원 심결 (폐곡선 분할 결합)', edition: null, location: '—', text_kind: 'summary', speaker: null, excerpt: '—', status: none('특허심판원 심결 요지 2015~2025 · "폐곡선 분할" 결합') },
        ],
      },
    ],
    further_review: ['D2 본문을 받은 뒤 결합 동기 문단 확인', '효과(명세서 [0088])가 현저한 효과로 인정된 사례'],
    ...common(unv('edition_unknown')),
  },
  'oa_1:42-4-2:c6': {
    bundle_id: 'le_3', unit_id: 'oa_1:42-4-2:c6', question: '명확성: 앞에 나오지 않은 "상기" 표현', as_of: null, checked_on: CHECKED_ON,
    claims: [
      {
        no: 1, text: "청구항에 '상기'로 가리키는 대상이 앞에 없으면 무엇을 가리키는지 불명확해 제42조제4항제2호 거절이유가 된다.", status: ok('심사기준 원문 대조'),
        sources: [
          { source_kind: 'statute', identifier: '특허법 제42조제4항제2호', edition: '시행 2099.1.1. (예시)', location: '제42조제4항제2호', text_kind: 'full', speaker: null, excerpt: '발명이 명확하고 간결하게 적혀 있을 것', status: ok('조문 원문 대조') },
          { source_kind: 'exam_guideline', identifier: '특허·실용신안 심사기준 제2부 제4장 (예시 위치)', edition: '2099.1. 개정 (예시)', location: '3.2 (4)', text_kind: 'full', speaker: null, excerpt: "'상기'로 인용한 용어가 앞에 없는 경우", status: ok('원문 대조') },
        ],
      },
    ],
    further_review: [],
    ...common(ok('주장마다 근거 원문 대조')),
  },
}

// ---- 법률 질문 (사건 없이) 예시 답 ----
export function exampleLegalAnswer(q: LegalQuestion): LegalEvidenceBundle {
  const base = exampleLegal['oa_1:29-2:c1']
  // 고른 자료 유형만 남기고(고르지 않으면 모두), 주장 상태는 남은 근거 중 가장 나쁜 값으로
  const claims = base.claims
    .map((c) => {
      const sources = c.sources.filter((s) => q.source_kinds.length === 0 || q.source_kinds.includes(s.source_kind))
      return { ...c, sources, status: worst(sources.map((s) => s.status), '근거 원문 대조') }
    })
    .filter((c) => c.sources.length > 0)
  return {
    ...base,
    bundle_id: 'le_chat_1',
    unit_id: null,
    question: q.text,
    as_of: q.as_of,
    claims,
    // 걸러 낸 뒤 남은 주장으로 묶음 상태를 다시 모은다
    status: worst(claims.map((c) => c.status), '주장마다 근거 원문 대조'),
  }
}
