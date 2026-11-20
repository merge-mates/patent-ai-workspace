import { wordDiff } from '../diff'

interface Props {
  before: string
  after: string
  // human: 사람이 고친 곳 (AI 원문 회색 취소선, 고친 글 파란 밑줄)
  // amend: 보정으로 바뀐 곳 (지운 글 빨간 취소선, 더한 글 초록 바탕) — 사람 표시와 헷갈리지 않게 색을 나눈다
  mode: 'human' | 'amend'
}

const styles = {
  human: {
    removed: { color: '#8c8c8c', textDecoration: 'line-through' },
    added: { color: '#1677FF', textDecoration: 'underline', textUnderlineOffset: 3 },
  },
  amend: {
    removed: { color: '#cf1322', textDecoration: 'line-through', background: '#fff1f0' },
    added: { background: '#d9f7be' },
  },
} as const

// 변경 추적: 두 글을 비교해 지운 곳·더한 곳을 표시한다
export function TrackedText({ before, after, mode }: Props) {
  return (
    <span style={{ lineHeight: 1.9 }}>
      {wordDiff(before, after).map((p, i) =>
        p.kind === 'same' ? (
          <span key={i}>{p.text}</span>
        ) : p.kind === 'removed' ? (
          <del key={i} style={styles[mode].removed}>
            {p.text}
          </del>
        ) : (
          <ins key={i} style={{ ...styles[mode].added, textDecorationSkipInk: 'none' }}>
            {p.text}
          </ins>
        ),
      )}
    </span>
  )
}
