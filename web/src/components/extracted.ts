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

// 충돌일 때 두 후보를 출처(규칙/모델)와 함께 한 줄 글로 (AI가 하나를 고르지 않는다)
export function candidatesText(v: Extracted): string {
  return v.candidates
    .map((c) => `${sourceName[c.source]} "${c.raw_text ?? String(c.value)}"${c.page ? ` (${c.page}쪽)` : ''}`)
    .join(' / ')
}
