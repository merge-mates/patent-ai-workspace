import { ApiError } from './errors'

// 서버는 /api/* 로만 부른다. 개발 서버가 FastAPI로 넘긴다 (vite.config.ts proxy).
// 경로는 docs/api/README.md v0 그대로 (앞에 /api만 붙임).
export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`)
  return readBody<T>(res)
}

export async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api${path}`, { method: 'POST', body: form })
  return readBody<T>(res)
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return readBody<T>(res)
}

export async function sendJson<T>(method: 'PUT' | 'PATCH', path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return readBody<T>(res)
}

async function readBody<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T
  // 오류 본문이 {code, message}가 아니어도 조용히 넘기지 않고 HTTP 코드로 알린다
  let code = `http_${res.status}`
  let message = `서버 오류 (${res.status})`
  let extra: Record<string, unknown> = {}
  try {
    const { code: c, message: m, ...rest } = (await res.json()) as Record<string, unknown>
    if (typeof c === 'string') code = c
    if (typeof m === 'string') message = m
    extra = rest // 나머지 칸은 버리지 않고 ApiError에 담는다
  } catch {
    // 본문이 JSON이 아님: 위 기본 문구 그대로
  }
  throw new ApiError(code, message, res.status, extra)
}
