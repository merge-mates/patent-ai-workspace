// 화면에 들어가기 전에 데이터를 받는 곳 (react-router loader). 화면 부품 안에서 따로 부르지 않는다.
import { api } from './api'
import type { CaseSummary } from './types/provisional/case'

export async function casesLoader(): Promise<CaseSummary[]> {
  return api.listCases()
}
