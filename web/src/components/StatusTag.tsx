import {
  CheckCircleOutlined,
  QuestionCircleOutlined,
  SearchOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { Tag, Tooltip } from 'antd'
import { unverifiedReasonLabel } from '../labels'
import type { Status, StatusValue } from '../types/generated/OAResult'

interface Props {
  // 상태 객체 전체 또는 값만 (표처럼 값만 있을 때)
  status: Status | StatusValue
  // 이유·찾아본 범위를 꼬리표 안에 붙일지 (좁은 칸에서는 끈다)
  detail?: boolean
}

// 상태 네 가지를 늘 같은 모양으로: 아이콘 + 한국어 글자 (색만으로 구분하지 않음)
// - 확인됨: 파란 꼬리표 + 체크
// - 확인되지 않음: 흰 바탕 점선 테두리 + 물음표 (+ 이유)
// - 조회 범위 내 없음: 회색 꼬리표 + 돋보기 (+ 찾아본 범위)
// - 충돌: 자주 꼬리표 + 경고 세모
export function StatusTag({ status, detail = true }: Props) {
  const s: Status =
    typeof status === 'string'
      ? { value: status, reason: null, checked: null, searched_scope: null }
      : status

  if (s.value === 'confirmed') {
    const tag = (
      <Tag color="blue" icon={<CheckCircleOutlined />}>
        확인됨
      </Tag>
    )
    // 무엇을 확인했나는 마우스를 올리면 보인다
    return s.checked ? <Tooltip title={s.checked}>{tag}</Tooltip> : tag
  }
  if (s.value === 'unverified') {
    const reason = s.reason ? unverifiedReasonLabel[s.reason] : null
    return (
      <Tag
        icon={<QuestionCircleOutlined />}
        style={{ background: '#fff', borderStyle: 'dashed', color: 'rgba(0,0,0,0.75)' }}
      >
        확인되지 않음{detail && reason ? ` · ${reason}` : ''}
      </Tag>
    )
  }
  if (s.value === 'not_found_in_scope') {
    return (
      <Tag icon={<SearchOutlined />} style={{ background: '#f0f0f0', color: 'rgba(0,0,0,0.65)' }}>
        조회 범위 내 없음{detail && s.searched_scope ? ` · ${s.searched_scope}` : ''}
      </Tag>
    )
  }
  return (
    <Tag color="magenta" icon={<WarningOutlined />}>
      충돌
    </Tag>
  )
}
