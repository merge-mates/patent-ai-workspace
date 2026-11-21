import type { ReactNode } from 'react'
import { wordDiff } from '../diff'

interface Props {
  before: string
  after: string
  // human: 사람이 고친 곳 (AI 원문 옅은 취소선, 고친 글 검정 굵은 밑줄) — "직접 고침" 검정 꼬리표와 같은 계열
  // amend: AI가 보정으로 바꾼 곳 (지운 글 옅은 글자에 줄, 더한 글 파랑) — 사람 표시와 겹치지 않게 색을 나눈다
  mode: 'human' | 'amend'
  // 글 조각을 그리는 방법 (식별번호를 링크로 바꿀 때)
  renderText?: (text: string) => ReactNode
}

const styles = {
  human: {
    removed: { color: 'var(--fg-neutral-tertiary)', textDecoration: 'line-through' },
    added: { color: '#171719', fontWeight: 700, textDecoration: 'underline', textUnderlineOffset: 3 },
  },
  amend: {
    removed: { color: 'var(--fg-neutral-tertiary)', textDecoration: 'line-through' },
    added: { color: '#0066ff', background: '#0066ff14', fontWeight: 600, padding: '1px 4px', borderRadius: 6 },
  },
} as const

// 변경 추적: 두 글을 비교해 지운 곳·더한 곳을 표시한다
export function TrackedText({ before, after, mode, renderText = (t) => t }: Props) {
  return (
    <span style={{ lineHeight: 1.9 }}>
      {wordDiff(before, after).map((p, i) =>
        p.kind === 'same' ? (
          <span key={i}>{renderText(p.text)}</span>
        ) : p.kind === 'removed' ? (
          <del key={i} style={styles[mode].removed}>
            {renderText(p.text)}
          </del>
        ) : (
          <ins key={i} style={{ ...styles[mode].added, textDecorationSkipInk: 'none' }}>
            {renderText(p.text)}
          </ins>
        ),
      )}
    </span>
  )
}
