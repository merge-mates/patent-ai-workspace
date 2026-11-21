import { Button } from 'antd'
import type { DirectTodo } from '../todos'
import { useTodoGo } from './useTodoGo'

// 직접 할 일 줄들. panel = 단계 막대 아래 회색 판(작게), page = 정리 단계 맨 위 목록(크게)
export function TodoRows({ todos, variant }: { todos: DirectTodo[]; variant: 'panel' | 'page' }) {
  const go = useTodoGo()
  const page = variant === 'page'
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      {todos.map((t) => (
        <div
          key={t.key}
          style={{
            display: 'flex',
            gap: page ? 16 : 12,
            alignItems: 'center',
            flexWrap: 'wrap',
            padding: page ? '14px 0' : '10px 0',
            borderBottom: page ? '1px solid var(--line-neutral-tertiary)' : undefined,
          }}
        >
          {page ? (
            <div style={{ flex: '1 1 300px', display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span className="body1" style={{ fontWeight: 600 }}>
                {t.title}
              </span>
              <span className="label1 t3">{t.desc}</span>
            </div>
          ) : (
            <>
              <span className="body2" style={{ fontWeight: 600 }}>
                {t.title}
              </span>
              <span className="label1 t3" style={{ flex: '1 1 240px' }}>
                {t.desc}
              </span>
            </>
          )}
          {page && t.go.kind === 'source' ? (
            <Button type="link" onClick={() => go(t.go)}>
              {t.go.label}
            </Button>
          ) : (
            <Button size={page ? 'middle' : 'small'} onClick={() => go(t.go)}>
              {t.go.label}
            </Button>
          )}
        </div>
      ))}
    </div>
  )
}
