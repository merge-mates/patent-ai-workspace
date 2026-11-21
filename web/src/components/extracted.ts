import type {
  ExtractedValueListInt,
  ExtractedValueListStr,
  ExtractedValueNoticeKind,
  ExtractedValueStr,
} from '../types/generated/OAResult'

// 뽑은 값 하나 (ExtractedValue). 뽑은 타입을 그대로 써서 스키마가 바뀌면 타입 검사가 잡는다
export type Extracted = ExtractedValueStr | ExtractedValueNoticeKind | ExtractedValueListInt | ExtractedValueListStr

// 후보 출처 글자. 뽑은 타입의 값이 늘면 Record 타입 검사가 잡는다
export const sourceName: Record<ExtractedValueStr['candidates'][number]['source'], string> = { rule: '규칙', model: '모델' }
