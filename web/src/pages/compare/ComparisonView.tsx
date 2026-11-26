import { AuditOutlined, CheckOutlined, DiffOutlined, EllipsisOutlined, RobotOutlined } from '@ant-design/icons'
import { Button, Table, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { type ReactNode, useContext, useState } from 'react'
import { useRouteLoaderData } from 'react-router'
import { claimLocationText, claimRange, scopeText, sentence } from '../../format'
import { CoreLabel, HumanCheckTag } from '../../components/Marks'
import { SourceContext } from '../../components/sourceContext'
import { locationLabels } from '../../components/citeLabels'
import { StatusTag } from '../../components/StatusTag'
import { differenceElements } from './differences'
import { COMPARE_UNVERIFIED_TEXT } from '../../labels'
import type { ComparisonRow, ComparisonTable, Judgment, NoveltySummary } from '../../types/generated/ComparisonTable'
import type { JudgmentUnit } from '../../types/generated/JudgmentUnit'
import type { OAResult } from '../../types/generated/OAResult'
import type { PageText } from '../../types/generated/PageText'
import type { OALoaderData } from '../../loaders'

// 표 한 줄 = 구성요소 하나 (그 구성요소의 인용발명별 대비 줄을 모은 것)
interface ElementLine {
  key: string
  claim: number
  element: string
  element_location: string
  rows: ComparisonRow[]
}

// 대비 결과 글자 (상태 네 가지와 다른 축). 색만으로 나누지 않게 아이콘도 붙인다
const judgmentTag: Record<Judgment, { color: string; text: string; icon: ReactNode }> = {
  disclosed: { color: 'green', text: '같은 구성', icon: <CheckOutlined /> },
  difference_candidate: { color: 'orange', text: '차이점 후보', icon: <DiffOutlined /> },
  unclear: { color: 'default', text: '판단 어려움', icon: <EllipsisOutlined /> },
}

const noveltyVerdictText: Record<NoveltySummary['verdict'], string> = {
  no_difference: '차이 없음',
  substantially_same_candidate: '실질적 동일 후보',
  different: '차이 있음',
}

// 핵심 한 덩어리의 한 줄 요약: 표 값으로 만들 수 있는 만큼만 (진보성: 차이점 후보 개수 + 첫 구성요소)
function headline(t: ComparisonTable): string {
  if (t.summary.kind === 'novelty') return `${t.summary.citation} 하나와 대비 · ${noveltyVerdictText[t.summary.verdict]}`
  const diffs = differenceElements(t)
  if (diffs.length > 0) return `차이점 후보 ${diffs.length}개 · “${diffs[0]}”${diffs.length > 1 ? ` 외 ${diffs.length - 1}개` : ''}`
  if (t.rows.length === 0) return '대비한 구성요소 줄이 아직 없어요'
  return '차이점 후보를 찾지 못했어요'
}

// 왜 가져왔나: 검색 내부 글자("hybrid 상위 10에서 9위")면 쉬운 말로, 아니면 그대로
function whyText(why: string): string {
  if (/hybrid|상위 \d+|\d+위|cite-idx/.test(why)) return '청구항 구성요소의 글자로 인용문헌에서 찾은 문단이에요.'
  return `왜 가져왔나: ${why}`
}

// 짧은 제목: 진보성은 "차이점 후보 N개"까지만 (구성요소 이름은 아래 목록)
function headlineShort(t: ComparisonTable): string {
  if (t.summary.kind === 'novelty') return headline(t)
  const n = diffNames(t).length
  if (n > 0) return `차이점 후보 ${n}개`
  return headline(t)
}

// 차이점 후보 구성요소 이름 (진보성만 목록으로 보인다. 신규성은 제목에 판정이 있다)
const diffNames = (t: ComparisonTable): string[] => (t.summary.kind === 'novelty' ? [] : differenceElements(t))

// 이 묶음 청구항에 대해 심사관이 짚은 인용 위치: 청구항 줄의 위치가 있으면 그것, 없으면 거절이유 인용문헌 칸.
// 위치마다 어느 청구항에 대해 짚었는지(claims)와, AI가 이 표에서 그 문단을 근거로 썼는지(used)를 같이 둔다.
// 구성요소와의 연결은 데이터에 없어 붙이지 않는다 (지어내지 않음)
function examinerSpots(oa: OAResult | null, unit: JudgmentUnit, t: ComparisonTable) {
  const rej = oa?.rejections.find((r) => r.no === unit.rejection)
  if (!oa || !rej) return []
  const out: { label: string; number: string; location: string; labels: string[]; claims: number[]; used: boolean }[] = []
  for (const c of rej.citations) {
    const number = c.number.value ?? c.number.raw_text
    if (!number) continue
    // 위치 글자 → 그 위치를 짚은 청구항들
    const byLoc = new Map<string, number[]>()
    for (const row of oa.claim_rows) {
      if (row.rejection !== unit.rejection || row.claim === null || !unit.claims.includes(row.claim)) continue
      for (const loc of row.locations[c.label] ?? []) byLoc.set(loc.trim(), [...(byLoc.get(loc.trim()) ?? []), row.claim])
    }
    if (byLoc.size === 0) for (const loc of c.cited_paragraphs.value ?? []) byLoc.set(loc.trim(), [])
    // AI가 이 표에서 근거로 쓴 그 인용문헌의 문단 표기
    const usedLabels = new Set(t.rows.flatMap((r) => r.evidence.filter((e) => e.document_id === number).map((e) => e.location)))
    for (const [loc, claims] of byLoc) {
      const labels = locationLabels(loc)
      if (labels)
        out.push({ label: c.label, number, location: loc, labels, claims: [...new Set(claims)].sort((x, y) => x - y), used: labels.some((l) => usedLabels.has(l)) })
    }
  }
  return out
}

// 통지서 원문에서 심사관 구성 대비표의 자리: "나. 구성 대비" 머리가 있는 쪽과 머리부터 다음 줄까지의 글자.
// 원문 판에서 그 글자를 강조해 표로 바로 간다. 못 찾으면 null (버튼을 그리지 않음)
function oaCompareTable(doc: PageText | null): { page: number; text: string } | null {
  for (const p of doc?.pages ?? []) {
    const m = /[가-힣]\.\s*구성\s*대비\s*\n[^\n]*/.exec(p.text ?? '')
    if (m) return { page: p.page, text: m[0] }
  }
  return null
}

// 구성 대비: 핵심(AI 제안) → 못 본 인용발명 → 구성요소 표(행을 누르면 오른쪽에 근거) → 따지는 순서 펼침
export function ComparisonView({ t, oa, unit }: { t: ComparisonTable; oa: OAResult | null; unit: JudgmentUnit }) {
  const spots = examinerSpots(oa, unit, t)
  const { openCite, openPage } = useContext(SourceContext)
  // 심사관 대비 칸(진보성): 지금은 통지서 구성 대비표 원문으로 잇는다. 구성요소별 심사관 판단은 다음 단계에서 붙인다
  const { document: oaDoc } = useRouteLoaderData('oa') as OALoaderData
  const oaTable = oaCompareTable(oaDoc)
  const [orderOpen, setOrderOpen] = useState(false)

  // 구성요소 한 줄에 인용발명(D1·D2)을 나란히 둔다 (심사관 구성 대비표처럼).
  // 데이터는 구성요소 × 인용발명마다 줄이 따로라서, 같은 구성요소의 줄을 모아 한 줄로 만든다
  const elementKey = (r: ComparisonRow) => `${r.claim}|${r.element_location}|${r.element}`
  const elements: ElementLine[] = []
  for (const r of t.rows) {
    const k = elementKey(r)
    let line = elements.find((x) => x.key === k)
    if (!line) {
      line = { key: k, claim: r.claim, element: r.element, element_location: r.element_location, rows: [] }
      elements.push(line)
    }
    line.rows.push(r)
  }
  // 표에 둘 인용발명 칸: 대비한 인용발명 순서대로 (줄에만 있는 이름도 뒤에 붙인다)
  const citeLabels = [...new Set([...t.citations.filter((c) => c.compared).map((c) => c.label), ...t.rows.map((r) => r.citation)])]

  // 줄 하나(구성요소 × 인용발명)를 오른쪽 판에 연다. 근거 문단이 없는 줄도 상태·찾아본 범위를 보인다
  const openRow = (r: ComparisonRow) =>
    openCite({
      title: `${r.citation} ${r.evidence[0]?.location ?? r.element_location}`.trim(),
      items: r.evidence,
      status: r.status,
      // 검색 순위·방식(hybrid, 몇 위)은 개발용이라 쉬운 말로 바꾼다
      note: r.why_retrieved ? whyText(r.why_retrieved) : null,
      unverifiedText: COMPARE_UNVERIFIED_TEXT,
      // 근거 문단이 없는 줄도 그 인용문헌 원문 전체는 열 수 있게 (표의 인용발명 번호)
      docId: r.evidence[0]?.document_id ?? t.citations.find((c) => c.label === r.citation)?.number ?? null,
    })

  const inventive = t.summary.kind === 'inventive_step'
  // 인용발명 칸 하나: 그 인용발명 줄마다 대비 결과 + 문단(누르면 오른쪽에) + 심사관 지정 표시
  const citeCell = (line: ElementLine, label: string) => {
    const rows = line.rows.filter((r) => r.citation === label)
    if (rows.length === 0) return <span className="t3">—</span>
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {rows.map((r, i) => {
          const where = [...new Set(r.evidence.map((e) => e.location).filter(Boolean))].join(', ')
          return (
            <div key={i} style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
              {/* 진보성은 인용발명을 결합해서 보므로 한 문헌에 없다고 차이점이 아니다:
                  인용문헌 칸에서는 "대응 기재 못 찾음"(회색)으로, 차이점 후보는 결론 칸에서만 말한다 */}
              {inventive && r.judgment === 'difference_candidate' ? (
                <Tag bordered={false} style={{ background: '#f0f0f0', color: 'rgba(0,0,0,0.65)' }}>
                  대응 기재 못 찾음
                </Tag>
              ) : (
                <Tag color={judgmentTag[r.judgment].color} icon={judgmentTag[r.judgment].icon} bordered={false}>
                  {judgmentTag[r.judgment].text}
                </Tag>
              )}
              <Button type="link" size="small" style={{ padding: 0, height: 'auto' }} onClick={() => openRow(r)}>
                {/* 근거 문단이 없으면 찾아본 범위를 오른쪽에 연다 */}
                {where || (r.judgment === 'difference_candidate' ? (inventive ? '찾아본 범위' : '대응 문단 못 찾음') : '문단 없음')}
              </Button>
              {r.evidence.length > 0 && r.paragraph_source === 'examiner' && (
                <Tooltip title="통지서에서 심사관이 짚은 문단">
                  <AuditOutlined style={{ color: 'var(--fg-neutral-tertiary)' }} />
                </Tooltip>
              )}
              {r.evidence.length > 0 && r.paragraph_source !== 'examiner' && (
                <Tooltip title="통지서에 없던 문단을 AI가 찾음">
                  <RobotOutlined style={{ color: '#722ed1' }} />
                </Tooltip>
              )}
              {r.status.value !== 'confirmed' && !(r.judgment === 'difference_candidate' && r.status.value === 'not_found_in_scope') && (
                <StatusTag status={r.status} detail={false} unverifiedText={COMPARE_UNVERIFIED_TEXT} />
              )}
            </div>
          )
        })}
      </div>
    )
  }

  // 결론 칸: 어느 인용발명에든 같은 구성이 있으면 "인용발명에 있음", 없고 차이점 후보가 있으면 "차이점 후보",
  // 모두 판단 어려움이면 "판단 어려움" (diffNames와 같은 기준)
  const conclusion = (line: ElementLine) => {
    const found = line.rows.filter((r) => r.judgment === 'disclosed')
    if (found.length > 0) {
      const where = found.map((r) => `${r.citation} ${[...new Set(r.evidence.map((e) => e.location).filter(Boolean))].join(', ')}`.trim())
      return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Tag color="green" icon={<CheckOutlined />} bordered={false} style={{ alignSelf: 'flex-start' }}>
            인용발명에 있음
          </Tag>
          <span className="label2 t3">{[...new Set(where)].join(' · ')}</span>
        </div>
      )
    }
    const diff = line.rows.some((r) => r.judgment === 'difference_candidate')
    return diff ? (
      <Tag color="orange" icon={<DiffOutlined />} bordered={false}>
        차이점 후보
      </Tag>
    ) : (
      <Tag icon={<EllipsisOutlined />} bordered={false}>
        판단 어려움
      </Tag>
    )
  }

  const columns: ColumnsType<ElementLine> = [
    {
      title: '구성요소',
      render: (_, line) => (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span>{line.element}</span>
          {/* "청구항 1 · 청구항 1 [구성 1-1]"처럼 겹치지 않게 위치 글자를 정리 */}
          <span className="label2 t3">{claimLocationText(line.claim, line.element_location)}</span>
        </div>
      ),
    },
    ...citeLabels.map((label) => ({
      title: label,
      width: 190,
      render: (_: unknown, line: ElementLine) => citeCell(line, label),
    })),
    {
      title: '결론',
      width: 150,
      render: (_, line) => conclusion(line),
    },
    // 진보성: 심사관이 통지서 구성 대비표에서 이 구성요소를 어떻게 봤는지 둘 자리.
    // 값은 아직 데이터에 없어 지어내지 않고, 통지서 표 원문으로 가는 링크만 둔다 (다음 단계: F1이 표를 구성요소별로 읽음)
    ...(inventive
      ? [
          {
            title: '심사관 대비 (통지서)',
            width: 150,
            render: () =>
              oaTable ? (
                <Button type="link" size="small" style={{ padding: 0, height: 'auto' }} onClick={() => openPage(oaTable.page, oaTable.text)}>
                  통지서 표에서 보기
                </Button>
              ) : (
                <span className="t3">—</span>
              ),
          },
        ]
      : []),
  ]

  // 대비하지 않은 인용발명 (지원 안 하는 나라 등): 위에 따로 알린다
  const skipped = t.citations.filter((c) => !c.compared)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <CoreLabel />
        <h2 className="heading1" style={{ fontSize: 24, lineHeight: '32px' }}>
          {headlineShort(t)}
        </h2>
        {/* 진보성: 차이점만이 아니라 심사관이 그 차이를 어떻게 메웠는지(결합 논리)를 바로 아래 한 줄로 */}
        {t.summary.kind === 'inventive_step' && t.summary.combination && (
          <div style={{ padding: '10px 14px', borderLeft: '3px solid var(--fg-neutral-tertiary)', background: 'var(--bg-neutral-secondary)', borderRadius: 4 }}>
            <span className="label2 t3">심사관은 이 차이를 이렇게 봤어요 (AI 요약 · 판정은 하지 않아요)</span>
            <div className="body2">{sentence(t.summary.combination)}</div>
          </div>
        )}
        {/* 차이점 후보 구성요소 이름은 제목에 다 넣으면 두세 줄이 되어 작게 목록으로 */}
        {diffNames(t).length > 0 && (
          <ul className="body2 t2" style={{ margin: 0, paddingLeft: 20 }}>
            {diffNames(t).map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        {t.summary.kind === 'novelty' && <p className="body1 t2">{sentence(t.summary.reason)} 판정은 하지 않아요.</p>}
        {/* 표가 "조회 범위 내 없음"이면 그 꼬리표와 찾아본 범위를 같이 */}
        {t.status.value !== 'confirmed' && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {/* 표 전체가 "조회 범위 내 없음"이어도 같은 구성을 찾은 줄이 있으면 "일부"라고 말한다 (머리와 줄이 어긋나 보이지 않게) */}
            {t.status.value === 'not_found_in_scope' && t.rows.some((r) => r.judgment === 'disclosed') ? (
              // 표가 구성요소 한 줄씩이라 개수도 구성요소로 센다: 어느 인용발명에서도 같은 구성을 못 찾은 구성요소
              <span className="label1 t2">
                구성요소 {diffNames(t).length}개는 {citeLabels.join('·')} 어디에서도 같은 구성을 찾지 못해 차이점 후보예요. 없다고
                단정하지는 않아요.
              </span>
            ) : (
              <>
                <StatusTag status={t.status} detail={false} unverifiedText={COMPARE_UNVERIFIED_TEXT} />
                {t.status.value === 'not_found_in_scope' && t.status.searched_scope && (
                  <span className="label1 t2">
                    같은 구성을 못 찾았어요 (찾아본 범위: {scopeText(t.status.searched_scope)}). 없다고 단정하지는 않아요.
                  </span>
                )}
              </>
            )}
          </div>
        )}
        {/* 본문을 못 봐서 대비하지 못한 인용발명 (지원 안 하는 나라 포함): 노란 직접 확인 줄 */}
        {skipped.map((c) => (
          <div key={c.label} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <HumanCheckTag>{c.skipped_reason?.includes('지원 안 하는 나라') ? '지원 안 하는 나라 · 직접 확인' : '직접 검토 필요'}</HumanCheckTag>
            <span className="label1 t2">
              인용발명 {c.label} {c.number}는 대비하지 않았어요{c.skipped_reason ? ` · ${c.skipped_reason}` : ''}
            </span>
            {c.skipped_status && c.skipped_status.value !== 'confirmed' && <StatusTag status={c.skipped_status} detail={false} unverifiedText={COMPARE_UNVERIFIED_TEXT} />}
          </div>
        ))}
      </div>

      {/* 심사관이 통지서에서 짚은 인용 문단: AI가 근거로 골랐든 아니든 늘 보이고, 누르면 원문 전체에서 그 문단을 연다 */}
      {spots.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <h3 className="headline1" style={{ margin: 0 }}>심사관이 짚은 문단</h3>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {spots.map((s) => (
              <Button
                key={`${s.label}-${s.location}`}
                size="small"
                icon={<AuditOutlined />}
                onClick={() =>
                  openCite({
                    title: `${s.label} ${s.location} · 심사관 지정`,
                    items: [],
                    status: { value: 'confirmed', reason: null, checked: '통지서에 적힌 인용 위치', searched_scope: null },
                    note: '통지서에서 심사관이 짚은 문단이에요. 아래 원문 전체에서 강조해 보여요.',
                    docId: s.number,
                    highlightLabels: s.labels,
                  })
                }
              >
                {s.label} {s.location}
                {/* 어느 청구항에 대해 짚었는지 · AI가 이 표에서 근거로 썼는지 */}
                <span className="label2 t3" style={{ marginLeft: 6 }}>
                  {s.claims.length > 0 ? `청구항 ${claimRange(s.claims)} · ` : ''}
                  {s.used ? 'AI 근거로 씀' : 'AI 근거에 없음'}
                </span>
              </Button>
            ))}
          </div>
          <span className="label2 t3">“AI 근거에 없음”은 심사관은 짚었지만 아래 표에 근거로 나오지 않은 문단이에요. 직접 확인해 주세요.</span>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h3 className="headline1">구성요소 · 문단을 누르면 오른쪽에 원문</h3>
        <Table<ElementLine>
          size="middle"
          rowKey={(line) => line.key}
          columns={columns}
          dataSource={elements}
          pagination={false}
          scroll={{ x: 640 }}
          locale={{ emptyText: '대비한 줄이 없습니다 (인용문헌 본문을 받으면 대비)' }}
        />
        {inventive && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Tag color="blue" bordered={false}>다음 단계</Tag>
            <span className="label2 t2">
              심사관 대비 칸에는 통지서 구성 대비표에서 심사관이 구성요소마다 본 판단(예: 일부 차이, 실질적 동일)을 읽어 붙여요. 지금은 통지서 표 원문으로 연결해요.
            </span>
            {oaTable && (
              <Button size="small" onClick={() => openPage(oaTable.page, oaTable.text)}>
                통지서 구성 대비표 보기 ({oaTable.page}쪽)
              </Button>
            )}
          </div>
        )}
        <span className="label2 t3">
          결론은 인용발명 어느 하나에 같은 구성이 있으면 “인용발명에 있음”, 없으면 “차이점 후보”예요. 문단 옆 표시는 심사관 지정(통지서에 적힌 문단)과 AI가 새로 찾은 문단을 나눠요.
        </span>
      </div>

      {/* 진보성만: 심사관이 따지는 순서(차이점 → 결합 → 효과 후보). 데이터에 있는 것만 */}
      {t.summary.kind === 'inventive_step' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Button type="text" onClick={() => setOrderOpen(!orderOpen)} style={{ alignSelf: 'flex-start' }}>
            {orderOpen ? '심사관이 따지는 순서 접기' : '심사관이 따지는 순서로 정리 보기'}
          </Button>
          {orderOpen && (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                paddingLeft: 16,
                borderLeft: '2px solid var(--line-neutral-secondary)',
              }}
            >
              <span className="body2">
                <b>① 차이점</b> {t.summary.differences.length === 0 ? '없음' : t.summary.differences.join(' / ')}
              </span>
              <span className="body2">
                <b>② 결합</b> {t.summary.combination}
              </span>
              <span className="body2">
                <b>③ 효과 후보</b> {t.summary.effect_candidates.length === 0 ? '없음' : t.summary.effect_candidates.join(' / ')}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
