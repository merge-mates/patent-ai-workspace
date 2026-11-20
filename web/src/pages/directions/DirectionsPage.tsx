import { CheckCircleTwoTone, CloseCircleTwoTone, ExclamationCircleTwoTone } from '@ant-design/icons'
import { App, Card, Descriptions, Empty, List, Popover, Radio, Space, Tag, Typography } from 'antd'
import { useState } from 'react'
import { Link, useLoaderData, useRouteLoaderData } from 'react-router'
import { api } from '../../api'
import { AmendmentLimitAlert, UnsupportedAlert } from '../../components/CaseAlerts'
import { ConfidenceTag, OriginTag } from '../../components/DirectionTags'
import { ExampleDataMark, HumanCheckTag } from '../../components/Marks'
import { StatusTag } from '../../components/StatusTag'
import { claimRange } from '../../format'
import { EvidenceText } from '../../components/EvidenceText'
import {
  addedSourceLabel,
  amendmentKindLabel,
  amendmentLimitLabel,
  rebuttalTypeLabel,
  rejectionKindLabel,
} from '../../labels'
import type { DirectionsLoaderData, OALoaderData } from '../../loaders'
import type {
  CoarseDirection,
  DirectionCandidate,
  DirectionCandidates,
  DirectionSelection,
} from '../../types/generated/DirectionCandidates'
import type { JudgmentUnit } from '../../types/generated/JudgmentUnit'

const coarseLabel: Record<CoarseDirection, string> = {
  argue_only: '반박만',
  amend_and_argue: '보정+반박',
  amend_only: '보정만',
}

// "자세히": 근거(원문 위치)와 확인 사항(권리범위가 얼마나 줄어드나)
function Detail({ c }: { c: DirectionCandidate }) {
  return (
    <div style={{ maxWidth: 380 }}>
      <Typography.Text strong>근거</Typography.Text>
      <ul style={{ margin: '4px 0 8px', paddingInlineStart: 18 }}>
        {c.evidence.length === 0 && <li>없음</li>}
        {c.evidence.map((e) => (
          <li key={`${e.document_id}-${e.location}-${e.raw_text}`}>
            <EvidenceText e={e} />
          </li>
        ))}
      </ul>
      <Typography.Text strong>확인 사항</Typography.Text>
      <ul style={{ margin: '4px 0 0', paddingInlineStart: 18 }}>
        {c.checks.map((x) => (
          <li key={x}>{x}</li>
        ))}
      </ul>
    </div>
  )
}

// 후보 한 줄: "1순위 · 방향 이름 · [확신]" + 짧은 이유 한 줄(늘 보임) + 자세히
function CandidateLine({ c }: { c: DirectionCandidate }) {
  return (
    <Space direction="vertical" size={0}>
      <Space size={6} wrap>
        <Typography.Text strong>{c.rank === null ? '—' : `${c.rank}순위`}</Typography.Text>
        <span>·</span>
        <Typography.Text>{c.name}</Typography.Text>
        <span>·</span>
        <ConfidenceTag c={c.confidence} />
        <Tag bordered={false}>{coarseLabel[c.coarse]}</Tag>
      </Space>
      <Space size={6} wrap>
        <Typography.Text type="secondary" style={{ fontSize: 13 }}>
          {c.reason}
        </Typography.Text>
        <Popover content={<Detail c={c} />} title="자세히" trigger="click">
          <Typography.Link style={{ fontSize: 13 }} onClick={(e) => e.preventDefault()}>
            자세히
          </Typography.Link>
        </Popover>
      </Space>
    </Space>
  )
}

// 고른 후보의 거절이유별 대응 · 보정 핵심 · 반박 논리 · 확인 사항
function Chosen({ c }: { c: DirectionCandidate }) {
  return (
    <Descriptions size="small" column={1} bordered style={{ marginTop: 8 }}>
      <Descriptions.Item label="거절이유별 대응">
        {c.per_rejection.map((r) => (
          <div key={r.rejection}>
            거절이유 {r.rejection}: {r.response}
          </div>
        ))}
      </Descriptions.Item>
      <Descriptions.Item label="보정 핵심">
        {c.amendment_core.length === 0
          ? '보정 없음'
          : c.amendment_core.map((a) => (
              <div key={`${a.claim}-${a.kind}`}>
                청구항 {a.claim}: {amendmentKindLabel[a.kind]}
                {a.source && (
                  <Typography.Text type="secondary"> (출처: {addedSourceLabel[a.source]})</Typography.Text>
                )}
              </div>
            ))}
      </Descriptions.Item>
      {c.rebuttal && (
        <Descriptions.Item label="반박 논리">
          {rebuttalTypeLabel[c.rebuttal.type]} — {c.rebuttal.summary}
        </Descriptions.Item>
      )}
      <Descriptions.Item label="확인 사항">
        {c.checks.map((x) => (
          <div key={x}>{x}</div>
        ))}
      </Descriptions.Item>
    </Descriptions>
  )
}

const unitTitle = (u: JudgmentUnit | undefined, unitId: string) =>
  u
    ? `거절이유 ${u.rejection} ${rejectionKindLabel[u.rejection_kind]} · 청구항 ${
        u.unit_kind === 'single_claim' ? u.representative_claim : `${u.representative_claim} 묶음 (${claimRange(u.claims)})`
      }`
    : unitId

// 4 대응 방향: 묶음마다 후보를 보고 고른다. 최종 선택은 사람이 한다 (AI는 기본값만)
export function DirectionsPage() {
  const { units, directions, caseCheck } = useLoaderData() as DirectionsLoaderData
  const { oaResult } = useRouteLoaderData('oa') as OALoaderData
  const { message } = App.useApp()
  // 묶음마다 지금 선택 (처음엔 서버가 준 값: AI 기본값 또는 비어 있음)
  const [chosen, setChosen] = useState<Record<string, DirectionSelection | null>>(() =>
    Object.fromEntries(directions.map((d) => [d.unit_id, d.selection])),
  )
  // 저장 중인 묶음들 (여러 묶음을 빨리 골라도 서로 덮지 않게 묶음마다 따로)
  const [saving, setSaving] = useState<Record<string, boolean>>({})

  // 사람이 고르면 서버에 저장한다 (저장한 선택은 1등과 같아도 "사람이 고름")
  const choose = async (d: DirectionCandidates, candidateId: string) => {
    setSaving((prev) => ({ ...prev, [d.unit_id]: true }))
    try {
      const saved = await api.selectDirection(d.unit_id, candidateId)
      // 응답이 늦게 와도 다른 묶음의 선택을 덮지 않게 그때의 최신 값에 더한다
      setChosen((prev) => ({ ...prev, [d.unit_id]: saved.selection }))
    } catch (e) {
      message.error(`저장하지 못했습니다: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving((prev) => ({ ...prev, [d.unit_id]: false }))
    }
  }

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <AmendmentLimitAlert noticeKind={oaResult?.result.notice_kind.value ?? null} />
      {caseCheck && (
        <UnsupportedAlert numbers={caseCheck.unsupported_rejections} rejections={oaResult?.result.rejections ?? []} />
      )}
      {directions.length === 0 && (
        <Card size="small" title="대응 방향">
          <Empty description="대응 방향 후보가 아직 없습니다" />
        </Card>
      )}
      {directions.map((d) => {
        const sel = chosen[d.unit_id]
        const picked = d.candidates.find((c) => c.candidate_id === sel?.candidate_id)
        return (
          <Card
            key={d.unit_id}
            size="small"
            title={
              <Space wrap>
                {unitTitle(
                  units.find((u) => u.unit_id === d.unit_id),
                  d.unit_id,
                )}
                {/* 보정 제한: 최초/최후. 모르면 값 없이 상태만 (없음으로 읽히지 않게) */}
                {d.amendment_limit.value ? (
                  <Tag>보정 제한: {amendmentLimitLabel[d.amendment_limit.value]}</Tag>
                ) : (
                  <Space size={2}>
                    <Tag>보정 제한</Tag>
                    <StatusTag status={d.amendment_limit.status} />
                  </Space>
                )}
                <ExampleDataMark />
              </Space>
            }
            extra={sel ? <OriginTag origin={sel.origin} /> : <HumanCheckTag>방향을 골라 주세요</HumanCheckTag>}
          >
            <Radio.Group
              value={sel?.candidate_id ?? null}
              disabled={saving[d.unit_id] === true}
              onChange={(e) => choose(d, e.target.value as string)}
              style={{ display: 'flex', flexDirection: 'column', gap: 10 }}
            >
              {d.candidates.map((c) => (
                <Radio key={c.candidate_id} value={c.candidate_id}>
                  <CandidateLine c={c} />
                </Radio>
              ))}
            </Radio.Group>
            {picked ? (
              <Chosen c={picked} />
            ) : (
              <Typography.Paragraph type="secondary" style={{ margin: '8px 0 0' }}>
                확신이 낮아 AI가 미리 고르지 않았습니다. 고를 때까지 이 묶음의 초안은 보류합니다.
              </Typography.Paragraph>
            )}
          </Card>
        )
      })}
      <Card size="small" title={<Space>사건 전체 검사 <ExampleDataMark /></Space>}>
        {caseCheck === null ? (
          <Space>
            <StatusTag status="unverified" />
            <Typography.Text type="secondary">사건 전체 검사 결과가 아직 없습니다</Typography.Text>
          </Space>
        ) : (
          <List
            size="small"
            dataSource={caseCheck.items}
            locale={{ emptyText: '검사 항목이 없습니다' }}
            renderItem={(it) => (
              <List.Item style={{ paddingInline: 0 }}>
                <Space align="start">
                  {it.result === 'ok' ? (
                    <CheckCircleTwoTone twoToneColor="#52c41a" />
                  ) : it.result === 'warn' ? (
                    <ExclamationCircleTwoTone twoToneColor="#faad14" />
                  ) : (
                    <CloseCircleTwoTone twoToneColor="#ff4d4f" />
                  )}
                  <Space direction="vertical" size={0}>
                    <Typography.Text strong>{it.name}</Typography.Text>
                    <Typography.Text type="secondary">{it.detail}</Typography.Text>
                  </Space>
                </Space>
              </List.Item>
            )}
          />
        )}
        <Link to="../drafts" relative="path">
          의견서·보정 초안 보기 →
        </Link>
      </Card>
    </Space>
  )
}
