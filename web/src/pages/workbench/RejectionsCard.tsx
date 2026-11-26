import { Alert, Button, Descriptions, Empty, Segmented, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useContext, useState } from 'react'
import { useLocation } from 'react-router'
import { FieldValue } from '../../components/FieldValue'
import { AiResultMark, HumanCheckTag } from '../../components/Marks'
import { candidatesText } from '../../components/extracted'
import { RejectionLaw } from '../../components/RejectionLaw'
import { HintsCard } from './HintsCard'
import { SourceLink } from '../../components/SourceLink'
import { CiteSpotButton } from '../../components/CiteSpotButtons'
import { SourceContext } from '../../components/sourceContext'
import { StatusTag } from '../../components/StatusTag'
import { claimRange, claimsText, termText } from '../../format'
import { articleLabel, rejectionKindLabel } from '../../labels'
import type { LegalEvidenceBundle } from '../../types/generated/LegalEvidenceBundle'
import type { ClaimRow, OAResult, Rejection } from '../../types/generated/OAResult'

// AI가 다루지 않는 거절이유만 꼬리표를 단다 ("문헌 대조형"·"문장 검토형"은 팀 안 분류라 변리사 화면에서 뺌)
function TypeTag({ rej }: { rej: Rejection }) {
  if (!rej.supported) return <Tag color="default">AI가 다루지 않음</Tag>
  return null
}

// 청구항 줄이 모두 "못 뽑음"(인용·위치·원문이 다 빈 줄)인지: 빈 줄 여러 개 대신 한 줄 안내로 바꾼다
const isEmptyRow = (row: ClaimRow) =>
  row.status.value !== 'confirmed' && row.citations.length === 0 && row.clarity_terms.length === 0 && row.same_as.length === 0

// "claim:3" → "청구항 3", "rejection:1" → "거절이유 1"
// 같은 취지 여러 개: 청구항 번호는 "청구항 1–5"처럼 범위로 묶는다 (거절이유 등은 그대로)
function sameAsList(items: string[]): string {
  const claims = items.map((x) => /^claim:(\d+)$/.exec(x)?.[1]).filter((n): n is string => n !== undefined).map(Number)
  const others = items.filter((x) => !/^claim:\d+$/.test(x)).map(sameAsText)
  return [...(claims.length ? [`청구항 ${claimRange(claims)}`] : []), ...others].join(', ')
}

// 끝 숫자 읽는 소리에 맞춰 "와/과" (1 일·3 삼·6 육·7 칠·8 팔·0 영·10 십 → 과, 그 밖 → 와)
function withWa(text: string): string {
  const last = /(\d+)\s*$/.exec(text)?.[1]
  if (!last) return `${text}와`
  const n = Number(last)
  const batchim = n % 10 === 0 ? n !== 0 : [1, 3, 6, 7, 8].includes(n % 10)
  return `${text}${batchim || n === 0 ? '과' : '와'}`
}

const sameAsText = (s: string) =>
  s.replace(/^claim:(\d+)$/, '청구항 $1').replace(/^rejection:(\d+)$/, '거절이유 $1')

// 거절이유 줄 한 줄 설명: 청구항 · 조문. 명확성은 조문 대신 OA가 짚은 문구(claim_rows.clarity_terms, 디자인 B)
// 문구가 하나도 없으면 조문을 그대로 둔다 (지어내지 않음)
function rejectionSub(rej: Rejection, rows: ClaimRow[]): string {
  if (rej.kind === 'clarity') {
    const terms = [...new Set(rows.filter((x) => x.rejection === rej.no).flatMap((x) => x.clarity_terms.map(termText)))]
    if (terms.length > 0)
      return `${claimsText(rej.claims)} · “${terms[0]}”${terms.length > 1 ? ` 외 ${terms.length - 1}개` : ''}`
  }
  return `${claimsText(rej.claims)} · 특허법 ${articleLabel(rej.article.value)}`
}

function locationText(row: ClaimRow): string {
  if (row.no_location) return row.no_location
  const parts = Object.entries(row.locations).map(([label, locs]) => `${label} ${locs.join(', ')}`)
  return parts.length > 0 ? parts.join(' / ') : '—'
}

// 인용문헌·위치 한 칸: 인용문헌마다 위치 버튼 (위치가 없으면 문헌 버튼). 누르면 원문에서 그 문단 강조
function CiteCell({ row, numbers }: { row: ClaimRow; numbers: Record<string, string> }) {
  if (row.no_location) return <span className="body2 t2">{row.no_location}</span>
  if (row.citations.length === 0) return <span className="t3">—</span>
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {row.citations.flatMap((label) => {
        const locs = row.locations[label] ?? []
        return locs.length > 0
          ? locs.map((loc) => <CiteSpotButton key={`${label}-${loc}`} label={label} number={numbers[label] ?? null} location={loc} />)
          : [<CiteSpotButton key={label} label={label} number={numbers[label] ?? null} location={null} />]
      })}
    </div>
  )
}

// 같은 내용(인용·위치·같은 취지·상태)인 이어진 청구항 줄을 한 줄로 합친다 ("제6–10항")
type ShownRow = ClaimRow & { claimsShown: number[] }
function mergeRows(rows: ClaimRow[]): ShownRow[] {
  const key = (r: ClaimRow) =>
    JSON.stringify([r.citations, r.locations, r.same_as, r.status.value, r.status.reason, r.no_location, r.clarity_terms, r.clarity_reason])
  const out: ShownRow[] = []
  for (const r of rows) {
    const last = out.at(-1)
    if (last && r.claim !== null && key(last) === key(r)) last.claimsShown.push(r.claim)
    else out.push({ ...r, claimsShown: r.claim === null ? [] : [r.claim] })
  }
  return out
}
const claimCell = (row: ClaimRow) => {
  const shown = (row as ShownRow).claimsShown
  if (shown && shown.length > 1) return `제${claimRange(shown)}항`
  return row.claim === null ? '모름' : `제${row.claim}항`
}

// 청구항 줄 표의 열 (거절이유별·청구항별 둘이 같이 쓴다). numbers: 인용 라벨 → 문헌 번호 (버튼으로 원문을 연다)
const rowColumns = (clarity: boolean, numbers: Record<string, string> = {}): ColumnsType<ClaimRow> => [
  ...(clarity
    ? [
        {
          title: '문제 표현',
          render: (_: unknown, row: ClaimRow) =>
            row.clarity_terms.length > 0 ? row.clarity_terms.map((t) => `'${termText(t)}'`).join(', ') : '—',
        },
        {
          title: '이유 (AI 참고)',
          render: (_: unknown, row: ClaimRow) => (
            <Typography.Text type="secondary">{row.clarity_reason ?? '—'}</Typography.Text>
          ),
        },
      ]
    : [
        // 인용과 인용 위치를 한 칸으로: 위치 버튼을 누르면 오른쪽 판에 인용문헌 원문을 열고 그 문단을 강조
        { title: '인용문헌 · 위치', render: (_: unknown, row: ClaimRow) => <CiteCell row={row} numbers={numbers} /> },
      ]),
  {
    // 통지서의 "동일한 취지로 / ~에서 기술한 바와 같이"를 칸 이름이 아니라 뜻으로 보인다
    title: '같은 이유로 본 청구항',
    render: (_, row) => (row.same_as.length ? `${withWa(sameAsList(row.same_as))} 같은 이유` : '—'),
  },
  { title: '상태', render: (_, row) => <StatusTag status={row.status} compact /> },
  {
    title: '원문',
    // 확인된 줄만 "원문", 아니면 "후보 위치" (F5)
    render: (_, row) => (
      <SourceLink page={row.page} rawText={row.raw_text} candidate={row.status.value !== 'confirmed'} />
    ),
  },
]

// 펼친 줄 안: 기존 카드의 정보를 그대로 (조문·대상 청구항·인용·심사관 논리 요지·청구항 줄 표) + 이 거절이유의 법리
function RejectionDetail({ rej, rows, legal }: { rej: Rejection; rows: ClaimRow[]; legal: LegalEvidenceBundle[] }) {
  return (
    <div className="row-detail">
      <Space size={6} wrap>
        <TypeTag rej={rej} />
        {rej.status.value !== 'confirmed' && <StatusTag status={rej.status} />}
      </Space>
      {!rej.supported && (
        <Alert
          type="warning"
          showIcon
          message={
            <Space wrap>
              AI가 다루지 않는 거절이유입니다. 정리·대비·초안을 만들지 않습니다.
              <HumanCheckTag>직접 검토 필요</HumanCheckTag>
            </Space>
          }
        />
      )}
      <Descriptions size="small" column={1} bordered>
        <Descriptions.Item label="조문">
          <FieldValue v={rej.article}>{rej.article.raw_text ?? articleLabel(rej.article.value)}</FieldValue>
        </Descriptions.Item>
        <Descriptions.Item label="대상 청구항">
          <FieldValue v={rej.claims}>{claimsText(rej.claims)}</FieldValue>
        </Descriptions.Item>
        {rej.citations.length > 0 && (
          <Descriptions.Item label="인용문헌·인용 위치">
            <Space direction="vertical" size={6}>
              {rej.citations.map((c) => (
                <Space key={c.label} size={6} wrap align="start">
                  <Tag>{c.label}</Tag>
                  <FieldValue v={c.number}>{c.number.value ?? c.number.raw_text ?? '번호 모름'}</FieldValue>
                  {!c.country_supported && <HumanCheckTag>지원 안 하는 나라 · 직접 확인</HumanCheckTag>}
                  {/* 인용 위치도 아래 청구항 표처럼 버튼: 누르면 그 인용문헌 원문에서 그 위치를 강조 */}
                  <FieldValue v={c.cited_paragraphs}>
                    {c.cited_paragraphs.value && c.cited_paragraphs.value.length > 0 ? (
                      <Space size={4} wrap>
                        {c.cited_paragraphs.value.map((loc) => (
                          <CiteSpotButton key={loc} label={c.label} number={c.number.value ?? c.number.raw_text} location={loc} />
                        ))}
                      </Space>
                    ) : (
                      (c.cited_paragraphs.raw_text ?? '위치 없음')
                    )}
                  </FieldValue>
                </Space>
              ))}
            </Space>
          </Descriptions.Item>
        )}
        <Descriptions.Item label="심사관 논리 요지">
          <FieldValue v={rej.examiner_reasoning}>
            {rej.examiner_reasoning.value ?? rej.examiner_reasoning.raw_text ?? '—'}
          </FieldValue>
        </Descriptions.Item>
      </Descriptions>
      {rej.supported && rows.length > 0 && rows.every(isEmptyRow) && (
        // 청구항마다 빈 줄을 늘어놓지 않고, 무엇을 못 했는지 한 줄로 알린다
        <Alert
          type="info"
          showIcon
          message={`청구항 ${claimRange(rows.map((x) => x.claim).filter((c): c is number => c !== null))}의 청구항별 인용문헌·인용 위치를 통지서에서 읽지 못했어요. 위 "인용문헌·인용 위치"와 통지서 원문을 직접 확인해 주세요.`}
        />
      )}
      {rej.supported && !(rows.length > 0 && rows.every(isEmptyRow)) && (
        <>
        <Table<ClaimRow>
          size="small"
          rowKey={(row, i) => `${row.claim}-${row.rejection}-${i}`}
          columns={[
            { title: '청구항', width: 90, render: (_, row) => claimCell(row) },
            ...rowColumns(
              rej.kind === 'clarity',
              Object.fromEntries(
                rej.citations
                  .map((c) => [c.label, c.number.value ?? c.number.raw_text] as const)
                  .filter((x): x is readonly [string, string] => !!x[1]),
              ),
            ),
          ]}
          // 값이 다 빈 줄은 표에 늘어놓지 않고 아래 한 줄로 묶고, 같은 내용 줄은 합친다
          dataSource={mergeRows(rows.filter((x) => !isEmptyRow(x)))}
          pagination={false}
          scroll={{ x: 640 }}
          locale={{ emptyText: '청구항 줄 없음' }}
        />
        <EmptyRowsLine rows={rows.filter(isEmptyRow)} />
        </>
      )}
      {/* 법리는 따로 단계가 아니라 이 거절이유 안에 */}
      <RejectionLaw rejection={rej.no} legal={legal} />
    </div>
  )
}

// 빈 청구항 줄 묶음 한 줄: "청구항 2–6, 8–10은 항마다 따로 적힌 내용을 통지서에서 찾지 못했어요" + 후보 위치
// (값이 없는 줄을 같은 모양으로 여러 개 늘어놓지 않는다. 숨기지는 않고 번호는 다 보인다)
function EmptyRowsLine({ rows }: { rows: ClaimRow[] }) {
  if (rows.length === 0) return null
  const nos = rows.map((x) => x.claim).filter((c): c is number => c !== null)
  const first = rows.find((x) => x.page !== null)
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <StatusTag status={rows[0].status} compact />
      <span className="label1 t2">
        청구항 {claimRange(nos)}은 항마다 따로 적힌 내용을 통지서에서 찾지 못했어요. 통지서 원문을 직접 확인해 주세요.
      </span>
      {first && <SourceLink page={first.page} rawText={first.raw_text} candidate />}
    </div>
  )
}

// 줄 하나의 공통 틀: 제목(120px) · 한 줄 설명 · 꼬리표 · 자세히
function Row({
  id,
  title,
  sub,
  tags,
  open,
  onToggle,
  children,
}: {
  id?: string
  title: string
  sub: string
  tags: React.ReactNode
  open: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div
      id={id}
      style={{
        padding: '16px 0',
        borderBottom: '1px solid var(--line-neutral-tertiary)',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="headline2" style={{ width: 120 }}>
          {title}
        </span>
        <span className="body2 t2" style={{ flex: '1 1 240px' }}>
          {sub}
        </span>
        {tags}
        <Button type="text" size="small" onClick={onToggle}>
          {open ? '접기' : '자세히'}
        </Button>
      </div>
      {open && children}
    </div>
  )
}

// 청구항별 줄 안: 그 청구항에 걸린 거절이유 줄들 (지금까지 청구항별 표의 정보)
function ClaimDetail({ rows, byNo }: { rows: ClaimRow[]; byNo: Map<number, Rejection> }) {
  const columns: ColumnsType<ClaimRow> = [
    {
      title: '거절이유',
      render: (_, row) => {
        const rej = row.rejection === null ? undefined : byNo.get(row.rejection)
        return rej ? `${rej.no} · ${rejectionKindLabel[rej.kind]}` : '모름'
      },
    },
    {
      title: '인용·위치 / 문제 표현',
      render: (_, row) =>
        row.clarity_terms.length > 0
          ? row.clarity_terms.map((t) => `'${termText(t)}'`).join(', ')
          : `${row.citations.join(' + ') || '—'} ${locationText(row) === '—' ? '' : `· ${locationText(row)}`}`,
    },
    // 인용문헌·위치 칸은 위에서 따로 그려서 뺀다
    ...rowColumns(false).slice(1),
  ]
  return (
    <div className="row-detail">
      <Table<ClaimRow>
        size="small"
        rowKey={(row, i) => `${row.claim}-${row.rejection}-${i}`}
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ x: 640 }}
        locale={{ emptyText: '청구항 줄 없음 (AI가 다루지 않는 거절이유예요)' }}
      />
    </div>
  )
}

// 보기·펼친 줄 상태. 눌렀을 때의 주소 key를 같이 적어 두어, 직접 할 일의 "거절이유 보기"처럼
// 새 주소(#rejection-<번호>)로 오면 그 주소를 따른다: 거절이유별로 바꾸고 그 줄을 펼친다 (effect 없이 계산)
interface ViewState {
  view: 'rejection' | 'claim'
  open: string[]
}

// 거절이유 정리: 제목 줄 + 거절이유별 줄 / 청구항별 줄. 카드 상자 없이 줄
export function RejectionsCard({ r, legal }: { r: OAResult; legal: LegalEvidenceBundle[] }) {
  const { openPage } = useContext(SourceContext)
  const location = useLocation()
  const [pressed, setPressed] = useState<(ViewState & { key: string }) | null>(null)
  const hashNo = /^#rejection-(\d+)$/.exec(location.hash)?.[1]
  const cur: ViewState =
    pressed?.key === location.key ? pressed : { view: 'rejection', open: hashNo ? [`r${hashNo}`] : [] }
  const set = (next: ViewState) => setPressed({ key: location.key, ...next })

  const toggle = (id: string) =>
    set({ ...cur, open: cur.open.includes(id) ? cur.open.filter((x) => x !== id) : [...cur.open, id] })

  // 심사 대상 청구항 수와, 그중 거절이유가 걸린 청구항 수 (데이터에 있는 값만)
  const examined = r.examined_claims.value
  // 거절이유가 걸린 청구항 = 청구항 줄이 있는 것 + 거절이유의 대상 청구항 (AI가 다루지 않는 거절이유는 줄이 없다)
  const rejected = new Set([
    ...r.claim_rows.map((x) => x.claim).filter((c): c is number => c !== null),
    ...r.rejections.flatMap((x) => x.claims.value ?? []),
  ])
  const allowable = r.examiner_hints.allowable_claims.value
  const summary = [
    examined ? `청구항 ${examined.length}개 중 ${rejected.size}개` : null,
    allowable && allowable.length > 0 ? `특허 가능한 청구항 ${claimRange(allowable)}` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const byNo = new Map(r.rejections.map((x) => [x.no, x]))
  // 보이는 순서: 통지서 순번 그대로 (오른쪽 원문 PDF와 같은 순서). AI가 다루지 않는 것은 "직접 검토 필요" 표시로 구분한다
  const ordered = [...r.rejections].sort((a, b) => a.no - b.no)
  const rank = new Map(ordered.map((x, i) => [x.no, i]))
  // 청구항별: 청구항 번호로 모은다 (모름(null)은 맨 뒤)
  const claimNos = [...new Set<number | null>([...r.claim_rows.map((x) => x.claim), ...rejected])].sort(
    (a, b) => (a ?? 9999) - (b ?? 9999),
  )
  const allowableNote = r.examiner_hints.allowable_claims

  return (
    <div id="rejections" style={{ display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
        <h2 className="heading2" style={{ flex: '1 1 auto' }}>
          거절이유 {r.rejections.length}건
        </h2>
        {/* 판 머리에 "AI 결과"는 한 번만 */}
        <AiResultMark />
        {summary && <span className="label1 t3">{summary}</span>}
        <Segmented
          size="small"
          value={cur.view}
          onChange={(v) => set({ ...cur, view: v as ViewState['view'] })}
          options={[
            { label: '거절이유별', value: 'rejection' },
            { label: '청구항별', value: 'claim' },
          ]}
        />
      </div>
      {/* 심사관 참고사항은 제목 줄 바로 아래 (AI 결과 묶음 안) */}
      <div style={{ marginBottom: 8 }}>
        <HintsCard h={r.examiner_hints} />
      </div>
      {r.rejections.length === 0 && <Empty description="거절이유를 찾지 못했습니다 (확인되지 않음)" />}
      {cur.view === 'rejection'
        ? ordered.map((rej) => {
            const id = `r${rej.no}`
            const isOpen = cur.open.includes(id)
            return (
              <Row
                key={rej.no}
                id={`rejection-${rej.no}`}
                title={`${rej.no} ${rejectionKindLabel[rej.kind]}`}
                sub={rejectionSub(rej, r.claim_rows)}
                tags={
                  <>
                    {!rej.supported && (
                      <HumanCheckTag>직접 검토 필요</HumanCheckTag>
                    )}
                    {rej.status.value !== 'confirmed' && <StatusTag status={rej.status} detail={false} />}
                  </>
                }
                open={isOpen}
                onToggle={() => {
                  toggle(id)
                  // 펼칠 때 오른쪽 원문 판을 그 거절이유 원문 쪽으로 (화면은 내리지 않음)
                  if (!isOpen) openPage(rej.article.page, rej.article.raw_text, false)
                }}
              >
                <RejectionDetail
                  rej={rej}
                  // 청구항 번호순 (모름(null)은 맨 뒤): 저장 순서대로 두면 1, 6, 7, …, 2처럼 섞인다
                  rows={r.claim_rows
                    .filter((row) => row.rejection === rej.no)
                    .sort((a, b) => (a.claim ?? 9999) - (b.claim ?? 9999))}
                  legal={legal}
                />
              </Row>
            )
          })
        : <>
            {claimNos.map((no) => {
              const id = `c${no}`
              const rows = r.claim_rows.filter((row) => row.claim === no)
              // 걸린 거절이유 = 청구항 줄의 거절이유 + 대상 청구항에 이 청구항이 든 거절이유 (위 거절이유별과 같은 순서)
              const nos = [
                ...new Set<number | null>([
                  ...rows.map((x) => x.rejection),
                  ...(no === null ? [] : r.rejections.filter((x) => x.claims.value?.includes(no)).map((x) => x.no)),
                ]),
              ].sort((a, b) => (a === null ? 9999 : (rank.get(a) ?? 9998)) - (b === null ? 9999 : (rank.get(b) ?? 9998)))
              const rejs = nos.map((n) => (n === null ? undefined : byNo.get(n)))
              // 거절이유가 둘 이상이거나 AI가 다루지 않는 것이 걸렸으면 직접 검토
              const warn = nos.length >= 2 || rejs.some((x) => !x || !x.supported)
              return (
                <Row
                  key={id}
                  title={no === null ? '청구항 모름' : `청구항 ${no}`}
                  sub={rejs
                    .map((x) =>
                      x
                        ? `거절이유 ${x.no} ${rejectionKindLabel[x.kind]}${x.supported ? '' : ' (AI가 다루지 않음)'}`
                        : '거절이유 모름',
                    )
                    .join(' · ')}
                  tags={warn && <HumanCheckTag>직접 검토 필요</HumanCheckTag>}
                  open={cur.open.includes(id)}
                  onToggle={() => toggle(id)}
                >
                  <ClaimDetail rows={rows} byNo={byNo} />
                </Row>
              )
            })}
            {/* 거절이유가 없고 심사관이 특허 가능하다고 한 청구항: 줄 하나 (상태 꼬리표 규칙 같음) */}
            {allowableNote.value && allowableNote.value.length > 0 && (
              <div
                style={{
                  display: 'flex',
                  gap: 12,
                  alignItems: 'center',
                  flexWrap: 'wrap',
                  padding: '16px 0',
                  borderBottom: '1px solid var(--line-neutral-tertiary)',
                }}
              >
                <span className="headline2" style={{ width: 120 }}>
                  청구항 {claimRange(allowableNote.value)}
                </span>
                <span className="body2 t2" style={{ flex: '1 1 240px' }}>
                  거절이유 없음 · 심사관이 특허 가능하다고 함
                  {allowableNote.candidates.length > 0 && ` (후보: ${candidatesText(allowableNote)})`}
                </span>
                {allowableNote.status.value !== 'confirmed' && <StatusTag status={allowableNote.status} detail={false} />}
                <SourceLink
                  page={allowableNote.page}
                  rawText={allowableNote.raw_text}
                  candidate={allowableNote.status.value !== 'confirmed'}
                />
              </div>
            )}
          </>}
    </div>
  )
}
