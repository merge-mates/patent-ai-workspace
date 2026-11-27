// 임시 타입: GET /citations/{doc_id} 응답 (core/f3_claim_compare/cited_text.py CitedDocument).
// 결과 스키마 생성 목록(web_schemas)에 없는 API 응답이라 여기 둔다.
export interface CitedPart {
  chunk_id: string
  kind: string // abstract | claim | body | figure_desc
  label: string
  text: string
}

export interface CitedDocument {
  doc_id: string
  index_version: string
  parts: CitedPart[]
}
