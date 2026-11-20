import { Alert, Button } from 'antd'
import type { PageText } from '../types/generated/PageText'
import { StatusTag } from './StatusTag'

// 근거 글자를 찾으면 왼쪽 파란 선 + 옅은 파랑 바탕 (디자인 B 고친 판)
const highlightStyle = {
  boxShadow: 'inset 2px 0 0 #0066ff',
  background: '#0066ff0d',
  padding: '2px 4px 2px 10px',
  color: 'var(--fg-neutral-primary)',
  boxDecorationBreak: 'clone',
} as const

interface Props {
  open: boolean
  page: number
  highlight: string | null
  // 원문을 못 받았으면 null
  document: PageText | null
  onToggle: () => void
}

// 오른쪽 "참고 원문" 판. 펴면 그 쪽 글자, 접으면 48px 세로 막대.
// 단계를 옮겨도 사건 틀이 상태를 들고 있어서 접힘이 유지된다
export function SourcePanel({ open, page, highlight, document, onToggle }: Props) {
  if (!open) {
    return (
      <aside
        style={{
          flex: '0 0 48px',
          background: 'var(--bg-neutral-secondary)',
          display: 'flex',
          justifyContent: 'center',
          paddingTop: 24,
        }}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-label="원문 펴기"
          style={{
            all: 'unset',
            cursor: 'pointer',
            writingMode: 'vertical-rl',
            fontSize: 14,
            lineHeight: '20px',
            fontWeight: 600,
            color: 'var(--fg-neutral-tertiary)',
            padding: '8px 4px',
          }}
        >
          원문 펴기
        </button>
      </aside>
    )
  }

  const text = document?.pages.find((p) => p.page === page)?.text ?? null
  const at = text && highlight ? text.indexOf(highlight) : -1

  return (
    <aside
      style={{
        flex: '1 1 440px',
        minWidth: 0,
        maxWidth: '100%',
        background: 'var(--bg-neutral-secondary)',
        padding: '24px 28px',
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <div style={{ flex: '1 1 auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span className="label2 t3">참고 원문</span>
          <span className="headline2">통지서 {page}쪽</span>
        </div>
        {document && document.status.value !== 'confirmed' && <StatusTag status={document.status} detail={false} />}
        <Button type="text" onClick={onToggle}>
          접기
        </Button>
      </div>
      {document === null ? (
        // 원문이 없어도 빈 판으로 두지 않는다
        <Alert type="info" showIcon message="원문을 받지 못했어요" />
      ) : (
        <>
          <span className="label2 t3">
            의견제출통지서 · 전체 {document.pages.length}쪽
          </span>
          {text === null ? (
            <Alert type="info" showIcon message="이 쪽의 원문 글자를 받지 못했습니다" />
          ) : (
            <>
              {highlight && at < 0 && (
                <Alert
                  type="warning"
                  showIcon
                  message="근거 글자를 이 쪽에서 그대로 찾지 못했습니다"
                  description={highlight}
                />
              )}
              <p
                className="body2r"
                style={{ whiteSpace: 'pre-wrap', margin: 0, color: 'var(--fg-neutral-secondary)', overflowWrap: 'anywhere' }}
              >
                {at < 0 || !highlight ? (
                  text
                ) : (
                  <>
                    {text.slice(0, at)}
                    <span style={highlightStyle}>{highlight}</span>
                    {text.slice(at + highlight.length)}
                  </>
                )}
              </p>
            </>
          )}
        </>
      )}
    </aside>
  )
}
