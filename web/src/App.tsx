import { useEffect, useState } from 'react'

type Health = 'checking' | 'ok' | 'down'

function App() {
  const [health, setHealth] = useState<Health>('checking')

  useEffect(() => {
    fetch('/api/health')
      .then((res) => (res.ok ? res.json() : Promise.reject(res.status)))
      .then((body: { status: string }) => setHealth(body.status === 'ok' ? 'ok' : 'down'))
      .catch(() => setHealth('down'))
  }, [])

  return (
    <main>
      <h1>거절은거절해</h1>
      <p>
        서버 상태: <strong data-testid="health">{health}</strong>
      </p>
    </main>
  )
}

export default App
