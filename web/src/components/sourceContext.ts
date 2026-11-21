import { createContext } from 'react'
import type { Evidence1 } from '../types/generated/ComparisonTable'
import type { LegalSource } from '../types/generated/LegalEvidenceBundle'
import type { Status } from '../types/generated/OAResult'

// "원문 n쪽" 링크·"가기" 버튼을 누르면 사건 틀(CaseShell)이 오른쪽 원문 판을 그 쪽으로 연다.
// 링크는 어디에 있든 이 함수만 부른다. 쪽을 모르면(null) 판만 펴고 보던 쪽은 그대로 둔다.
// scroll=false면 판을 새로 펴지 않고 화면도 내리지 않는다 (줄을 펼치는 "자세히"처럼 보던 자리를 지킬 때)
export type OpenSource = (page: number | null, rawText: string | null, scroll?: boolean) => void

// 법률 근거 하나를 판에 연다. checkedOn은 그 근거가 든 묶음의 확인 기준일 (근거에 따로 없을 때 쓴다)
export type OpenEvidence = (source: LegalSource, checkedOn: string) => void

// 대비 줄·대응 방향 후보 근거처럼 공통 근거 위치(Evidence)를 판에 연다.
// title은 판 머리 글, status는 그 줄의 상태, note는 덧붙일 한 줄(왜 가져왔나 등)
export interface CiteRef {
  title: string
  items: Evidence1[]
  status: Status
  note: string | null
}
export type OpenCite = (ref: CiteRef) => void

export interface SourceActions {
  openPage: OpenSource
  openEvidence: OpenEvidence
  openCite: OpenCite
}

export const SourceContext = createContext<SourceActions>({ openPage: () => {}, openEvidence: () => {}, openCite: () => {} })
