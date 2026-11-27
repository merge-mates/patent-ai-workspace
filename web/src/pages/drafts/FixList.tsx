import { Alert, Button, Tag } from 'antd'
import { useContext } from 'react'
import { Link } from 'react-router'
import { SourceContext } from '../../components/sourceContext'
import type { Fix } from './coverage'

// 제출 전에 고칠 곳: 카드 대신 줄. 꼬리표(충돌 빨강 / 누락 노랑) + 굵은 한 줄 + 오른쪽 버튼
export function FixList({
  fixes,
  caseItems,
  hasCheck,
  onShowClaims,
  onShowOpinion,
}: {
  fixes: Fix[] | null
  caseItems: { name: string; result: 'warn' | 'fail' | 'ok'; detail: string }[]
  hasCheck: boolean
  onShowClaims: () => void
  onShowOpinion: (title: string) => void
}) {
  const { openPage } = useContext(SourceContext)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <h2 className="heading2" style={{ marginBottom: 8 }}>
        {fixes === null ? '제출 전에 고칠 곳' : `제출 전에 고칠 곳 ${fixes.length}`}
      </h2>
      {fixes === null && <Alert type="warning" showIcon message="초안 검사 결과가 아직 없어요 · 누락과 번호 일치를 직접 확인해 주세요" />}
      {fixes?.length === 0 && <span className="body1 t2">고칠 곳으로 잡힌 것이 없어요. 제출 전에 한 번 더 직접 읽어 주세요.</span>}
      {fixes?.map((f) => (
        <div
          key={f.key}
          style={{
            display: 'flex',
            gap: 16,
            alignItems: 'center',
            padding: '14px 0',
            borderBottom: '1px solid var(--line-neutral-tertiary)',
            flexWrap: 'wrap',
          }}
        >
          <Tag color={f.tag === 'conflict' ? 'error' : 'warning'} bordered={false} style={{ marginInlineEnd: 0 }}>
            {f.tag === 'conflict' ? '충돌' : '누락'}
          </Tag>
          <div style={{ flex: '1 1 280px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            <span className="body1" style={{ fontWeight: 600 }}>
              {f.title}
            </span>
            {f.sub && <span className="label1 t3">{f.sub}</span>}
          </div>
          {f.action?.kind === 'source' && (
            <Button type="link" onClick={() => openPage(f.action?.kind === 'source' ? f.action.page : null, f.action?.kind === 'source' ? f.action.rawText : null)}>
              원문 보기
            </Button>
          )}
          {f.action?.kind === 'pick' && (
            <Link to="../directions" relative="path">
              <Button>고르기</Button>
            </Link>
          )}
          {f.action?.kind === 'claims' && <Button onClick={onShowClaims}>보정 청구항 보기</Button>}
          {f.action?.kind === 'opinion' && (
            <Button onClick={() => onShowOpinion(f.action?.kind === 'opinion' ? f.action.title : '')}>의견서 그 칸 보기</Button>
          )}
        </div>
      ))}
      {caseItems.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 16 }}>
          <h3 className="headline1" style={{ margin: 0 }}>{`사건 전체 검사 · 확인할 것 ${caseItems.length}`}</h3>
          {caseItems.map((it) => (
            <div key={`${it.name}-${it.detail}`} style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '8px 0', borderBottom: '1px solid var(--line-neutral-tertiary)', flexWrap: 'wrap' }}>
              <Tag color={it.result === 'fail' ? 'error' : 'default'} bordered={false} style={{ marginInlineEnd: 0 }}>
                {it.result === 'fail' ? '충돌' : '확인할 것'}
              </Tag>
              <div style={{ flex: '1 1 280px', display: 'flex', flexDirection: 'column' }}>
                <span className="body2" style={{ fontWeight: 600 }}>{it.name}</span>
                <span className="label1 t3">{it.detail}</span>
              </div>
            </div>
          ))}
        </div>
      )}
      {!hasCheck && <span className="label2 t3">사건 전체 검사 결과가 아직 없어요 (확인되지 않음)</span>}
    </div>
  )
}
