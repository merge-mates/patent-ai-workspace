import { AuditOutlined, CheckOutlined, DiffOutlined, EllipsisOutlined, RobotOutlined } from '@ant-design/icons'
import { Button, Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { type ReactNode, useContext, useState } from 'react'
import { claimLocationText, scopeText, sentence } from '../../format'
import { CoreLabel, HumanCheckTag } from '../../components/Marks'
import { SourceContext } from '../../components/sourceContext'
import { StatusTag } from '../../components/StatusTag'
import { COMPARE_UNVERIFIED_TEXT } from '../../labels'
import type { ComparisonRow, ComparisonTable, Judgment, NoveltySummary } from '../../types/generated/ComparisonTable'

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
  const diffs = t.rows.filter((r) => r.judgment === 'difference_candidate')
  if (diffs.length > 0) return `차이점 후보 ${diffs.length}개 · “${diffs[0].element}”${diffs.length > 1 ? ` 외 ${diffs.length - 1}개` : ''}`
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

// 차이점 후보 구성요소 이름: 인용발명 어느 하나에서 "같은 구성"으로 찾은 구성요소는 뺀다
// (같은 구성요소가 D1·D2 줄로 두 번 있어도 한 번만)
const diffNames = (t: ComparisonTable): string[] => {
  if (t.summary.kind === 'novelty') return []
  const found = new Set(t.rows.filter((r) => r.judgment === 'disclosed').map((r) => r.element))
  return [...new Set(t.rows.filter((r) => r.judgment === 'difference_candidate' && !found.has(r.element)).map((r) => r.element))]
}

// 구성 대비: 핵심(AI 제안) → 못 본 인용발명 → 구성요소 표(행을 누르면 오른쪽에 근거) → 따지는 순서 펼침
export function ComparisonView({ t }: { t: ComparisonTable }) {
  const { openCite } = useContext(SourceContext)
  const [orderOpen, setOrderOpen] = useState(false)

  const columns: ColumnsType<ComparisonRow> = [
    {
      title: '구성요소',
      render: (_, r) => (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span>{r.element}</span>
          {/* "청구항 1 · 청구항 1 [구성 1-1]"처럼 겹치지 않게 위치 글자를 정리 */}
          <span className="label2 t3">{claimLocationText(r.claim, r.element_location)}</span>
        </div>
      ),
    },
    {
      title: '인용발명 문단',
      width: 130,
      // 같은 문단이 근거로 두 번 와도 한 번만 ("[0044], [0044]" 방지)
      render: (_, r) => `${r.citation} ${[...new Set(r.evidence.map((e) => e.location).filter(Boolean))].join(', ') || '—'}`,
    },
    {
      // 심사관이 짚은 문단과 AI가 새로 찾은 문단은 이 열로만 구분한다 (스키마 값은 둘뿐)
      title: '찾은 곳',
      width: 150,
      render: (_, r) =>
        // 근거 문단이 없는 줄(찾아봤지만 못 찾음)은 "AI가 새로 찾음"이 아니다: 빈칸으로
        r.evidence.length === 0 ? (
          <span className="t3">—</span>
        ) : r.paragraph_source === 'examiner' ? (
          <Tag icon={<AuditOutlined />} bordered={false}>
            심사관 지정
          </Tag>
        ) : (
          <Tag icon={<RobotOutlined />} color="purple" bordered={false}>
            AI가 새로 찾음
          </Tag>
        ),
    },
    {
      title: '대비 결과',
      width: 230,
      render: (_, r) => (
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
          <Tag color={judgmentTag[r.judgment].color} icon={judgmentTag[r.judgment].icon} bordered={false}>
            {judgmentTag[r.judgment].text}
          </Tag>
          {/* 확인됨은 꼬리표를 달지 않는다. 확인되지 않음·조회 범위 내 없음·충돌만 */}
          {r.status.value !== 'confirmed' && <StatusTag status={r.status} detail={false} unverifiedText={COMPARE_UNVERIFIED_TEXT} />}
        </div>
      ),
    },
  ]

  const skipped = t.citations.filter((c) => !c.compared)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 40 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <CoreLabel />
        <h2 className="heading1" style={{ fontSize: 24, lineHeight: '32px' }}>
          {headlineShort(t)}
        </h2>
        {/* 차이점 후보 구성요소 이름은 제목에 다 넣으면 두세 줄이 되어 작게 목록으로 */}
        {diffNames(t).length > 0 && (
          <ul className="body2 t2" style={{ margin: 0, paddingLeft: 20 }}>
            {diffNames(t).map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        <p className="body1 t2">
          {sentence(t.summary.kind === 'novelty' ? t.summary.reason : t.summary.combination)} 판정은 하지 않아요.
        </p>
        {/* 표가 "조회 범위 내 없음"이면 그 꼬리표와 찾아본 범위를 같이 */}
        {t.status.value !== 'confirmed' && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            {/* 표 전체가 "조회 범위 내 없음"이어도 같은 구성을 찾은 줄이 있으면 "일부"라고 말한다 (머리와 줄이 어긋나 보이지 않게) */}
            {t.status.value === 'not_found_in_scope' && t.rows.some((r) => r.judgment === 'disclosed') ? (
              <span className="label1 t2">
                구성요소 {t.rows.filter((r) => r.status.value === 'not_found_in_scope').length}줄은 인용발명에서 대응 문단을 찾지
                못했어요{t.status.searched_scope ? ` (찾아본 범위: ${scopeText(t.status.searched_scope)})` : ''}. 없다고 단정하지는 않아요.
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

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h3 className="headline1">구성요소 · 행을 누르면 오른쪽에 그 문단</h3>
        <Table<ComparisonRow>
          size="middle"
          rowKey={(r) => `${r.claim}-${r.element_location}-${r.citation}-${r.paragraph_source}-${r.evidence[0]?.location ?? ''}-${r.element}`}
          columns={columns}
          dataSource={t.rows}
          pagination={false}
          scroll={{ x: 640 }}
          locale={{ emptyText: '대비한 줄이 없습니다 (인용문헌 본문을 받으면 대비)' }}
          onRow={(r) => ({
            // 모든 줄이 누르면 오른쪽 판에 열린다. 근거 위치가 없는 줄(찾아봤지만 못 찾음)도 상태·찾아본 범위·왜 가져왔나를 보인다
            onClick: () =>
              openCite({
                title: `${r.citation} ${r.evidence[0]?.location ?? r.element_location}`.trim(),
                items: r.evidence,
                status: r.status,
                // 검색 순위·방식(hybrid, 몇 위)은 개발용이라 쉬운 말로 바꾼다
                note: r.why_retrieved ? whyText(r.why_retrieved) : null,
                unverifiedText: COMPARE_UNVERIFIED_TEXT,
              }),
            style: { cursor: 'pointer' },
          })}
        />
        <span className="label2 t3">
          “심사관 지정”은 통지서에 적힌 문단, “AI가 새로 찾음”은 통지서에 없던 문단이에요. 왜 가져왔는지는 행을 누르면 오른쪽에 보여요.
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
