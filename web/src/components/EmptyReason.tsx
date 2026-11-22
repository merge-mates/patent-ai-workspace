import { StatusTag } from './StatusTag'

// 결과 목록이 빈 이유 한 줄 (서버 empty_reason, docs/api/README.md 19줄).
// 빈 목록을 "0건"·"없음"으로만 그리지 않고 왜 비었는지를 보인다 (못 찾음 ≠ 없음).
// 서버 글자의 앞머리로 갈라 보인다:
//   "넘김: <이유>"          → 단계를 넘김 · <이유>
//   "보류: <기다리는 것>"   → 보류 · <기다리는 것>
//   "확인되지 않음: <이유>" → [확인되지 않음] 꼬리표 · <이유>
//   그 밖 (예: "해당 거절이유 없음") → 글자 그대로
// 이유 안의 서버 영어 코드는 한국어로 바꿔 보인다. 모르는 코드는 그대로 둔다 (지어내지 않음).

// 넘긴 이유 앞머리 (core/agents/orchestrator.py "tool_missing: …", step_inputs.py "input_unverified: …")
const skipCodeLabel: Record<string, string> = {
  tool_missing: '도구 없음',
  input_unverified: '입력 확인되지 않음',
}

// 보류 이유 괄호 안 waiting_for 값 (core/agents/orchestrator.py, F5 design 6절 표)
const waitingForCodeLabel: Record<string, string> = {
  application_number: '출원번호 입력',
  dispatch_number: '발송번호 확인',
}

function koreanize(body: string): string {
  const m = /^([a-z_]+): (.*)$/.exec(body)
  let out = m && skipCodeLabel[m[1]] ? `${skipCodeLabel[m[1]]} · ${m[2]}` : body
  out = out.replace(/\(([a-z_]+)\)/g, (whole, code: string) =>
    waitingForCodeLabel[code] ? `(${waitingForCodeLabel[code]})` : whole,
  )
  return out
}

export function EmptyReason({ what, reason }: { what: string; reason: string }) {
  const [head, ...rest] = reason.split(': ')
  const body = koreanize(rest.join(': '))
  let shown: React.ReactNode = reason
  if (body && head === '넘김') shown = `단계를 넘겼어요 · ${body}`
  else if (body && head === '보류') shown = `보류 · ${body}`
  else if (body && head === '확인되지 않음')
    shown = (
      <>
        <StatusTag status="unverified" detail={false} /> {body}
      </>
    )
  return (
    <span className="body2 t2" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      <span className="label1">{what} 결과 없음</span>
      <span className="t3">·</span>
      <span>{shown}</span>
    </span>
  )
}
