import { CheckOutlined, CloseOutlined, EditOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Empty, Input, Space, Switch, Table, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link, useLoaderData, useRouteLoaderData } from 'react-router'
import { api, API_MODE } from '../../api'
import { UnsupportedAlert } from '../../components/CaseAlerts'
import { HumanEditedTag } from '../../components/DirectionTags'
import { ExampleDataMark, HumanCheckTag } from '../../components/Marks'
import { EvidenceText } from '../../components/EvidenceText'
import { TrackedText } from '../../components/TrackedText'
import type { DraftsLoaderData, OALoaderData } from '../../loaders'
import type { AmendedClaim } from '../../types/generated/Drafts'
import type { DraftCheck, DraftPatch, DraftsWithCheck } from '../../types/provisional/pending'

// 고치는 중인 곳: 의견서 칸 하나 또는 보정 청구항 하나 (보낼 요청과 같은 모양)
type Editing = DraftPatch | null

// 초안이 바탕으로 삼은 선택과 지금 선택을 견준 결과
// - changed: 다른 후보를 골랐음 → 이 초안은 이전 방향으로 만든 것
// - picked: 보류였던 묶음에서 이제 방향을 골랐음 → 다시 돌려야 초안이 생김
type BasisNote = 'changed' | 'picked' | null

// 의견서 한 칸의 글: AI 원본 보기면 AI 글만, 아니면 고친 곳을 변경 추적으로
function SectionText({ ai, human, showAi }: { ai: string; human: string | null; showAi: boolean }) {
  if (showAi || human === null) return <span style={{ lineHeight: 1.9 }}>{ai}</span>
  return <TrackedText before={ai} after={human} mode="human" />
}

function ClaimItem({
  c,
  showAi,
  note,
  onEdit,
}: {
  c: AmendedClaim
  showAi: boolean
  note: BasisNote
  onEdit: () => void
}) {
  if (c.ai_text === null && note === 'picked') {
    return (
      <Card size="small" type="inner" title={`청구항 ${c.claim}`}>
        <Alert
          type="info"
          showIcon
          message="방향을 골랐습니다. 이 묶음의 초안은 실행을 다시 돌리면 만들어집니다"
          description={API_MODE === 'mock' ? 'mock 예시 초안은 바뀌지 않습니다' : undefined}
        />
      </Card>
    )
  }
  if (c.ai_text === null) {
    // 확신 낮은 묶음: 사람이 방향을 고를 때까지 초안을 만들지 않는다
    return (
      <Card size="small" type="inner" title={`청구항 ${c.claim}`}>
        <Alert
          type="warning"
          showIcon
          message={
            <Space wrap>
              <span>보류: 방향을 골라 주세요</span>
              <Link to="../directions" relative="path">
                대응 방향으로 가기 →
              </Link>
            </Space>
          }
          description={c.held_reason}
        />
      </Card>
    )
  }
  return (
    <Card
      size="small"
      type="inner"
      title={`청구항 ${c.claim} (보정 초안)`}
      extra={
        <Button size="small" icon={<EditOutlined />} onClick={onEdit}>
          고치기
        </Button>
      }
    >
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        {note === 'changed' && (
          <Alert
            type="warning"
            showIcon
            message="고른 방향이 바뀌었습니다. 이 초안은 이전 방향으로 만든 것이라 다시 확인 필요"
          />
        )}
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            바뀐 부분 (OA 당시 청구항 → 보정 초안)
          </Typography.Text>
          <div>
            <TrackedText before={c.before} after={c.ai_text} mode="amend" />
          </div>
        </div>
        {c.human_text !== null && !showAi && (
          <div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              사람이 고친 곳 (AI 초안 → 고친 글)
            </Typography.Text>
            <div>
              <TrackedText before={c.ai_text} after={c.human_text} mode="human" />
            </div>
          </div>
        )}
        <div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            최초 명세서 근거 위치
          </Typography.Text>
          <ul style={{ margin: 0, paddingInlineStart: 18 }}>
            {c.spec_basis.length === 0 && <li>찾지 못함</li>}
            {c.spec_basis.map((b) => (
              <li key={`${b.document_id}-${b.location}-${b.raw_text}`}>
                <EvidenceText e={b} />
              </li>
            ))}
          </ul>
        </div>
      </Space>
    </Card>
  )
}

// 누락 검사(거절이유 × 대상 청구항)와 번호 불일치
function CheckCard({ check }: { check: DraftCheck }) {
  const missing = check.coverage.filter((x) => !x.covered).length
  return (
    <Card
      size="small"
      title={
        <Space>
          초안 검사 <ExampleDataMark />
        </Space>
      }
      extra={missing > 0 ? <HumanCheckTag>{`빠진 곳 ${missing}곳 · 직접 확인`}</HumanCheckTag> : null}
    >
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Table
          size="small"
          rowKey={(r) => `${r.rejection}-${r.claim}`}
          pagination={false}
          dataSource={check.coverage}
          columns={[
            { title: '거절이유', dataIndex: 'rejection' },
            { title: '대상 청구항', dataIndex: 'claim', render: (n: number) => `제${n}항` },
            {
              title: '의견서에서',
              render: (_, r) =>
                r.covered ? (
                  <Tag color="green" icon={<CheckOutlined />}>
                    다룸
                  </Tag>
                ) : (
                  <Tag color="red" icon={<CloseOutlined />}>
                    안 다룸
                  </Tag>
                ),
            },
            { title: '다룬 곳', render: (_, r) => r.where ?? '—' },
          ]}
        />
        {check.number_mismatches.map((m) => (
          <Alert key={m.where + m.detail} type="warning" showIcon message={`번호 불일치 · ${m.where}`} description={m.detail} />
        ))}
      </Space>
    </Card>
  )
}

// 5 의견서·보정 초안: 사람이 고친 곳은 변경 추적으로 보이고, AI 원본은 늘 남긴다
export function DraftsPage() {
  const { drafts: initial, directions, caseCheck } = useLoaderData() as DraftsLoaderData
  const { oaResult } = useRouteLoaderData('oa') as OALoaderData
  const { message } = App.useApp()
  const [drafts, setDrafts] = useState<DraftsWithCheck | null>(initial)
  const [showAi, setShowAi] = useState(false)
  const [editing, setEditing] = useState<Editing>(null)

  if (drafts === null) {
    return (
      <Card size="small" title="의견서·보정 초안">
        <Empty
          description={
            API_MODE === 'mock'
              ? "초안이 아직 없습니다 (예시 데이터는 '가상의 영상 처리 장치' 사건에만 있음)"
              : '초안이 아직 없습니다'
          }
        />
      </Card>
    )
  }

  // 고친 글을 저장한다. AI 원본은 서버가 그대로 남긴다
  const save = async () => {
    if (!editing) return
    try {
      setDrafts(await api.patchDraft(drafts.draft_id, editing))
      setEditing(null)
    } catch (e) {
      message.error(`저장하지 못했습니다: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const editor = (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      <Input.TextArea
        autoSize={{ minRows: 3, maxRows: 10 }}
        value={editing?.text}
        onChange={(e) => editing && setEditing({ ...editing, text: e.target.value })}
      />
      <Space>
        <Button size="small" type="primary" onClick={save}>
          저장
        </Button>
        <Button size="small" onClick={() => setEditing(null)}>
          취소
        </Button>
      </Space>
    </Space>
  )

  // 사람이 고친 곳 수는 판마다 따로 센다 (의견서 / 보정 청구항)
  // 사람이 고친 곳은 origin(human_edited)으로 센다
  const opinionEdited = drafts.opinion.filter((x) => x.origin === 'human_edited').length
  const claimsEdited = drafts.claims.filter((x) => x.origin === 'human_edited').length
  // 묶음마다 지금 선택과 초안의 바탕 선택을 견준다
  const noteOf = (unitId: string): BasisNote => {
    const now = directions.find((d) => d.unit_id === unitId)?.selection?.candidate_id ?? null
    const basis = drafts.based_on.find((b) => b.unit_id === unitId)?.candidate_id ?? null
    if (basis === null) return now === null ? null : 'picked'
    return now !== basis ? 'changed' : null
  }
  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {caseCheck && (
        <UnsupportedAlert numbers={caseCheck.unsupported_rejections} rejections={oaResult?.result.rejections ?? []} />
      )}
      <Card
        size="small"
        title={
          <Space wrap>
            의견서 초안 <ExampleDataMark />
            {opinionEdited > 0 && <HumanEditedTag count={opinionEdited} />}
          </Space>
        }
        extra={
          <Space size={6}>
            <Typography.Text style={{ fontSize: 12 }}>AI 원본 보기</Typography.Text>
            <Switch size="small" checked={showAi} onChange={setShowAi} />
          </Space>
        }
      >
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          {drafts.opinion.map((s, i) => (
            <div key={s.key}>
              <Space style={{ width: '100%', justifyContent: 'space-between' }}>
                <Typography.Text strong>
                  {i + 1}. {s.title}
                </Typography.Text>
                {editing?.section !== s.key && (
                  <Button
                    size="small"
                    type="text"
                    icon={<EditOutlined />}
                    onClick={() => setEditing({ section: s.key, text: s.human_text ?? s.ai_text })}
                  >
                    고치기
                  </Button>
                )}
              </Space>
              <div>{editing?.section === s.key ? editor : <SectionText ai={s.ai_text} human={s.human_text} showAi={showAi} />}</div>
            </div>
          ))}
        </Space>
      </Card>
      <Card
        size="small"
        title={
          <Space wrap>
            보정 청구항 초안 <ExampleDataMark />
            {claimsEdited > 0 && <HumanEditedTag count={claimsEdited} />}
          </Space>
        }
        extra={<HumanCheckTag>보정 적법성은 판단하지 않음 · 직접 판단</HumanCheckTag>}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {drafts.claims.map((c) =>
            editing?.claim === c.claim ? (
              <Card key={c.claim} size="small" type="inner" title={`청구항 ${c.claim} 고치기`}>
                {editor}
              </Card>
            ) : (
              <ClaimItem
                key={c.claim}
                c={c}
                showAi={showAi}
                note={noteOf(c.unit_id)}
                onEdit={() => setEditing({ claim: c.claim, text: c.human_text ?? c.ai_text ?? '' })}
              />
            ),
          )}
        </Space>
      </Card>
      <CheckCard check={drafts.check} />
    </Space>
  )
}
