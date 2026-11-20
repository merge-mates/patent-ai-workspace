// 예시 데이터: ⑤ 대응 방향 후보 · 의견서·보정 초안 · 초안 검사 · 사건 전체 검사.
// F2~F4 설계 뒤 뽑은 타입으로 바꿈. 화면 모양을 보려는 가짜 값이다 (가짜 통지서 fixture 사건 셋에 맞춤).
import type { Status, UnverifiedReason } from '../generated/OAResult'
import type { ResultCommon } from './analysis'
import type { CaseCheck, DirectionCandidates, Drafts } from './direction'

const ok = (checked: string): Status => ({ value: 'confirmed', reason: null, checked, searched_scope: null })
const unv = (reason: UnverifiedReason): Status => ({ value: 'unverified', reason, checked: null, searched_scope: null })
const common = (status: Status): ResultCommon => ({
  status, evidence: [], origin: 'ai_generated', needs_recheck: false, recheck_reason: null, flags: [],
})

// ---- ⑤ 대응 방향 후보 (판단 단위마다) ----
export const exampleDirections: Record<string, DirectionCandidates[]> = {
  oa_1: [
    {
      unit_id: 'oa_1:29-1-1:c1', ...common(unv('ambiguous')),
      selection: { candidate_id: 'd1a', origin: 'ai_default' },
      candidates: [
        {
          candidate_id: 'd1a', rank: 1, coarse: 'amend_and_argue', name: '구성 1-4를 독립항에 더하고 차이를 반박', confidence: 'high',
          reason: 'D1에 영역별 노출 제어가 없어 더하면 차이가 분명해짐',
          evidence: [{ text: '나눈 영역마다 노출을 따로 정한다', location: '최초 명세서 [0052]' }, { text: 'D1 본문에 영역별 노출 없음', location: 'D1 전체 (조회 범위 내 없음)' }],
          checks: ['청구항 1이 "영역별 노출 제어"까지로 좁아짐 (종속항 4의 범위)', '종속항 4는 삭제하거나 인용항을 고쳐야 함'],
          per_rejection: [{ rejection: 1, response: '신규성: 보정한 청구항 1은 D1과 구성 1-4에서 다름' }],
          amendment_core: [{ claim: 1, kind: '부가', source: '종속항 4 / 명세서 [0052]' }],
          rebuttal: { type: '차이점', summary: 'D1은 프리뷰 전체에 노출 하나를 쓴다' },
        },
        {
          candidate_id: 'd1b', rank: 2, coarse: 'argue_only', name: '보정 없이 도 4b는 폐곡선 분할이 아니라고 반박', confidence: 'medium',
          reason: '도 4b의 영역 표시는 격자라 폐곡선과 다르다고 볼 여지',
          evidence: [{ text: '도 4b 격자형 영역 표시', location: 'D1 도 4b' }],
          checks: ['권리범위는 그대로', '도면만으로 다툼이라 심사관이 받아들이지 않을 수 있음'],
          per_rejection: [{ rejection: 1, response: '신규성: 구성 1-3이 D1에 없음' }],
          amendment_core: [],
          rebuttal: { type: '차이점', summary: 'D1 도 4b는 사각 격자 분할' },
        },
      ],
    },
    {
      unit_id: 'oa_1:29-2:c1', ...common(unv('body_missing')),
      selection: { candidate_id: 'd2a', origin: 'ai_default' },
      candidates: [
        {
          candidate_id: 'd2a', rank: 1, coarse: 'amend_and_argue', name: '구성 1-4 부가 + 결합 동기 없음 반박', confidence: 'medium',
          reason: 'D2 본문을 못 받아 결합 동기 반박은 확인되지 않음',
          evidence: [{ text: '역광 장면의 프리뷰가 바로 보인다', location: '최초 명세서 [0088]' }],
          checks: ['청구항 1이 영역별 노출 제어까지로 좁아짐', 'D2 본문을 받으면 결합 동기 문단 다시 확인'],
          per_rejection: [{ rejection: 2, response: '진보성: 차이점(구성 1-4)과 효과([0088])로 반박' }],
          amendment_core: [{ claim: 1, kind: '부가', source: '종속항 4 / 명세서 [0052]' }],
          rebuttal: { type: '결합 동기 없음 · 현저한 효과', summary: 'D1·D2 어디에도 영역별 노출 제어를 결합할 암시가 없음' },
        },
        {
          candidate_id: 'd2b', rank: 2, coarse: 'amend_only', name: '청구항 1 삭제, 청구항 5를 독립항으로', confidence: 'medium',
          reason: '심사관 힌트가 없어 청구항 5가 살아날지는 불확실',
          evidence: [{ text: '청구항 5: 폐곡선 경계를 흐리게 처리', location: 'OA 당시 청구항 5' }],
          checks: ['권리범위가 청구항 5 범위로 크게 줄어듦'],
          per_rejection: [{ rejection: 2, response: '진보성: 청구항 5 구성은 D1·D2에 없음' }],
          amendment_core: [{ claim: 1, kind: '삭제', source: null }, { claim: 5, kind: '독립항으로', source: '청구항 1+5' }],
          rebuttal: null,
        },
      ],
    },
    {
      unit_id: 'oa_1:42-4-2:c6', ...common(ok('명세서 정의 대조')),
      selection: { candidate_id: 'd3a', origin: 'ai_default' },
      candidates: [
        {
          candidate_id: 'd3a', rank: 1, coarse: 'amend_only', name: '청구항 6의 인용항을 청구항 1로 고침', confidence: 'high',
          reason: "'프리뷰 이미지'는 청구항 1에 있어 인용항만 바꾸면 명확해짐",
          evidence: [{ text: '프리뷰 이미지란 촬영 전에 화면에 보이는 축소 영상', location: '최초 명세서 [0031]' }],
          checks: ['권리범위 변화 거의 없음 (인용 관계만 바뀜)'],
          per_rejection: [{ rejection: 3, response: '명확성: 인용항 정정으로 대응' }],
          amendment_core: [{ claim: 6, kind: '명확화 (인용항 정정)', source: null }],
          rebuttal: null,
        },
      ],
    },
    {
      // 확신 낮은 묶음: 순위 없이, 미리 고르지 않는다
      unit_id: 'oa_1:42-4-2:c7', ...common(unv('ambiguous')),
      selection: null,
      candidates: [
        {
          candidate_id: 'd4a', rank: null, coarse: 'amend_only', name: "'모듈들'을 청구항 1의 구성으로 특정", confidence: 'low',
          reason: '명세서에 모듈 정의가 없어 무엇으로 특정할지 정해야 함',
          evidence: [{ text: '모듈 정의 없음', location: '최초 명세서 전체 (조회 범위 내 없음)' }],
          checks: ['어느 구성으로 특정하느냐에 따라 범위가 달라짐'],
          per_rejection: [{ rejection: 3, response: '명확성: 특정해 대응' }],
          amendment_core: [{ claim: 7, kind: '명확화', source: '청구항 1' }],
          rebuttal: null,
        },
        {
          candidate_id: 'd4b', rank: null, coarse: 'amend_only', name: '청구항 7 삭제', confidence: 'low',
          reason: '종속항이라 빼도 청구항 1 범위는 그대로',
          evidence: [],
          checks: ['청구항 7의 보호를 잃음'],
          per_rejection: [{ rejection: 3, response: '명확성: 삭제로 대응' }],
          amendment_core: [{ claim: 7, kind: '삭제', source: null }],
          rebuttal: null,
        },
      ],
    },
  ],
  oa_2: [
    {
      unit_id: 'oa_2:29-2:c1', ...common(ok('인용 위치 대조')),
      selection: { candidate_id: 'e1a', origin: 'ai_default' },
      candidates: [
        {
          candidate_id: 'e1a', rank: 1, coarse: 'argue_only', name: '보정 없이 차이점(주변 온도 보정)으로 반박', confidence: 'high',
          reason: 'D1은 고정 상수 보정이라 차이가 분명함',
          evidence: [{ text: '주변 온도에 따라 보정값을 바꾼다', location: '최초 명세서 [0040]' }],
          checks: ['권리범위 그대로', 'D2(JP)는 대비하지 않아 직접 확인 필요'],
          per_rejection: [{ rejection: 1, response: '진보성: 구성 1-2가 D1에 없음' }],
          amendment_core: [],
          rebuttal: { type: '차이점', summary: 'D1 [0031]은 고정 상수' },
        },
      ],
    },
  ],
  oa_3: [
    {
      unit_id: 'oa_3:29-2:c1', ...common(unv('body_missing')),
      selection: null,
      candidates: [
        {
          candidate_id: 'f1a', rank: null, coarse: 'amend_and_argue', name: '청구항 5를 청구항 1에 넣어 감축', confidence: 'low',
          reason: '인용문헌 본문을 못 받아 대비가 없음',
          evidence: [{ text: '「특허 가능한 청구항」 청구항 5, 7', location: '통지서 3쪽' }],
          checks: ['최후거절이유통지라 청구범위 감축 등만 가능', '청구항 1이 청구항 5 범위로 줄어듦'],
          per_rejection: [{ rejection: 1, response: '진보성: 특허 가능한 청구항 5로 감축' }],
          amendment_core: [{ claim: 1, kind: '한정 (청구항 5 부가)', source: '청구항 5' }],
          rebuttal: null,
        },
      ],
    },
    {
      unit_id: 'oa_3:42-4-2:c1', ...common(ok('명세서 정의 대조')),
      selection: { candidate_id: 'f2a', origin: 'ai_default' },
      candidates: [
        {
          candidate_id: 'f2a', rank: 1, coarse: 'amend_only', name: "'약'을 명세서의 ±5% 범위로 바꿈", confidence: 'high',
          reason: '명세서 [0019]가 범위를 정함',
          evidence: [{ text: '설정값의 ±5% 안', location: '최초 명세서 [0019]' }],
          checks: ['특허법 제47조제3항 각 호 중 무엇에 해당하는지 직접 확인'],
          per_rejection: [{ rejection: 2, response: '명확성: 수치 범위로 명확화' }],
          amendment_core: [{ claim: 1, kind: '명확화', source: '명세서 [0019]' }],
          rebuttal: null,
        },
      ],
    },
  ],
}

// ---- 사건 전체 검사 ----
export const exampleCaseChecks: Record<string, CaseCheck> = {
  oa_1: {
    unsupported_rejections: [4],
    items: [
      { name: '거절이유마다 방향이 있나', result: 'warn', detail: '거절이유 4(제42조제3항)는 AI가 다루지 않음' },
      { name: '묶음끼리 보정이 부딪히나', result: 'ok', detail: '거절이유 1·2 모두 구성 1-4 부가로 같은 방향' },
      { name: '방향을 안 고른 묶음', result: 'warn', detail: '거절이유 3 청구항 7 (확신 낮음)' },
    ],
  },
  oa_2: {
    unsupported_rejections: [2],
    items: [
      { name: '거절이유마다 방향이 있나', result: 'warn', detail: '거절이유 2(제42조제3항)는 AI가 다루지 않음' },
      { name: '지원 안 하는 나라 인용문헌', result: 'warn', detail: 'D2(JP)는 대비하지 않음 · 직접 확인' },
    ],
  },
  oa_3: {
    unsupported_rejections: [],
    items: [
      { name: '보정 제한', result: 'warn', detail: '최후거절이유통지: 고른 보정이 허용되는 종류인지 직접 확인' },
      { name: '방향을 안 고른 묶음', result: 'warn', detail: '거절이유 1 청구항 1 묶음 (확신 낮음)' },
    ],
  },
}

// ---- 의견서·보정 청구항 초안 ----
export const exampleDrafts: Record<string, Drafts> = {
  oa_1: {
    draft_id: 'dr_1', ...common(ok('초안 검사')),
    based_on: [
      { unit_id: 'oa_1:29-1-1:c1', candidate_id: 'd1a' },
      { unit_id: 'oa_1:29-2:c1', candidate_id: 'd2a' },
      { unit_id: 'oa_1:42-4-2:c6', candidate_id: 'd3a' },
    ],
    opinion: [
      { key: 'case_info', title: '사건 정보', ai_text: '출원번호 10-2099-0000002, 발송번호 9-5-2099-000000002 의견제출통지서에 대하여 다음과 같이 의견을 제출합니다.', human_text: null },
      { key: 'points', title: '지적 요지', ai_text: '심사관은 청구항 1이 인용발명 1과 같고(신규성), 청구항 1~13이 인용발명 1·2의 결합으로 쉽게 발명할 수 있으며(진보성), 청구항 6·7의 표현이 불명확하다고 하였습니다.', human_text: null },
      {
        key: 'response', title: '대응과 근거',
        ai_text: '보정한 청구항 1은 나눈 영역마다 노출을 따로 정하는 구성을 포함합니다. 인용발명 1은 프리뷰 전체에 노출 하나를 적용하므로 이 구성이 없습니다. 따라서 보정한 청구항 1은 인용발명 1과 다르다고 주장합니다.',
        human_text: '보정한 청구항 1은 분할된 각 영역마다 노출을 독립적으로 정하는 구성을 포함합니다. 인용발명 1은 프리뷰 전체에 단일 노출을 적용하므로 이 구성이 없습니다. 따라서 보정한 청구항 1은 신규성이 있습니다.',
      },
      { key: 'amendment', title: '보정 설명', ai_text: '청구항 1에 종속항 4의 구성을 더하였고(최초 명세서 [0052]), 청구항 6의 인용항을 청구항 1로 고쳤습니다.', human_text: null },
      { key: 'closing', title: '마무리', ai_text: '이상과 같이 보정하고 의견을 제출하오니 검토해 주시기 바랍니다.', human_text: '이상과 같이 거절이유가 모두 해소되었다고 사료되므로 특허 결정을 하여 주시기 바랍니다.' },
    ],
    claims: [
      {
        claim: 1, unit_id: 'oa_1:29-2:c1',
        before: '영상을 촬영하는 카메라 모듈; 촬영 영상에서 프리뷰 이미지를 만드는 처리부; 및 프리뷰 이미지를 폐곡선으로 나누는 분할부를 포함하는 영상 처리 장치.',
        after: '영상을 촬영하는 카메라 모듈; 촬영 영상에서 프리뷰 이미지를 만드는 처리부; 프리뷰 이미지를 폐곡선으로 나누는 분할부; 및 나눈 영역마다 노출을 따로 정하는 제어부를 포함하는 영상 처리 장치.',
        human_text: null,
        spec_basis: [{ text: '분할된 영역마다 노출값을 따로 정한다', location: '최초 명세서 [0052]' }, { text: '청구항 4', location: '최초 청구범위' }],
        held_reason: null,
      },
      {
        claim: 6, unit_id: 'oa_1:42-4-2:c6',
        before: '제5항에 있어서, 상기 프리뷰 이미지의 경계를 흐리게 처리하는 영상 처리 장치.',
        after: '제1항에 있어서, 상기 프리뷰 이미지의 경계를 흐리게 처리하는 영상 처리 장치.',
        human_text: null,
        spec_basis: [{ text: '프리뷰 이미지란 촬영 전에 화면에 보이는 축소 영상', location: '최초 명세서 [0031]' }],
        held_reason: null,
      },
      {
        claim: 7, unit_id: 'oa_1:42-4-2:c7',
        before: '제1항에 있어서, 상기 모듈들은 서로 연결되는 영상 처리 장치.',
        after: null, human_text: null, spec_basis: [],
        held_reason: '확신 낮은 묶음이라 방향을 고를 때까지 초안을 만들지 않음',
      },
    ],
    check: {
      coverage: [
        { rejection: 1, claim: 1, covered: true, where: '대응과 근거 1문단' },
        { rejection: 2, claim: 1, covered: true, where: '대응과 근거 1문단' },
        { rejection: 2, claim: 5, covered: false, where: null },
        { rejection: 3, claim: 6, covered: true, where: '보정 설명' },
        { rejection: 3, claim: 7, covered: false, where: null },
      ],
      number_mismatches: [{ where: '보정 설명', detail: '"종속항 4"를 청구항 1에 더했는데 청구항 4를 지우거나 고친 내용이 없음' }],
    },
  },
}
