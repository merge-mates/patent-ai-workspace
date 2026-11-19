import { Alert, Drawer, Typography } from 'antd'
import type { PageText } from '../../types/generated/PageText'

interface Props {
  open: boolean
  page: number | null
  highlight: string | null
  document: PageText | null
  onClose: () => void
}

// 원문 쪽 글자를 그대로 보이고, 근거 글자를 노란 바탕으로 강조한다
export function SourceDrawer({ open, page, highlight, document, onClose }: Props) {
  const text = document?.pages.find((p) => p.page === page)?.text ?? null
  const at = text && highlight ? text.indexOf(highlight) : -1

  return (
    <Drawer title={`원문 ${page ?? ''}쪽`} open={open} onClose={onClose} width={520}>
      {text === null ? (
        <Alert type="info" showIcon message="이 쪽의 원문 글자를 받지 못했습니다" />
      ) : (
        <>
          {highlight && at < 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message="근거 글자를 이 쪽에서 그대로 찾지 못했습니다"
              description={highlight}
            />
          )}
          <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
            {at < 0 || !highlight ? (
              text
            ) : (
              <>
                {text.slice(0, at)}
                <mark style={{ background: '#fff1b8', padding: '0 2px' }}>{highlight}</mark>
                {text.slice(at + highlight.length)}
              </>
            )}
          </Typography.Paragraph>
        </>
      )}
    </Drawer>
  )
}
