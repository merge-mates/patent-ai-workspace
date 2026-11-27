import { AuditOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useContext } from 'react'
import { locationLabels } from './citeLabels'
import { SourceContext } from './sourceContext'

// 심사관이 짚은 인용 위치 버튼 하나: 누르면 오른쪽 판에 그 인용문헌 원문 전체를 열고 그 문단을 "심사관 지정"으로 강조
export function CiteSpotButton({
  label,
  number,
  location,
}: {
  label: string
  number: string | null
  location: string | null
}) {
  const { openCite } = useContext(SourceContext)
  const labels = location ? locationLabels(location.trim()) : null
  const text = `${label}${location ? ` ${location}` : ''}`
  // 문헌 번호를 모르면 열 수 없다: 글자만
  if (!number) return <span className="body2">{text}</span>
  return (
    <Button
      size="small"
      icon={<AuditOutlined />}
      onClick={() =>
        openCite({
          title: `${text} · 심사관 지정`,
          items: [],
          status: { value: 'confirmed', reason: null, checked: '통지서에 적힌 인용 위치', searched_scope: null },
          note: labels
            ? '통지서에서 심사관이 짚은 문단이에요. 아래 원문 전체에서 강조해 보여요.'
            : location
              ? `통지서 표기 "${location}"는 문단으로 바로 찾을 수 없어 원문 전체만 보여요.`
              : '통지서에 인용 위치가 없어 원문 전체만 보여요.',
          docId: number,
          highlightLabels: labels ?? [],
        })
      }
    >
      {text}
    </Button>
  )
}
