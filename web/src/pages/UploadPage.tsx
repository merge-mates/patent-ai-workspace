import { InboxOutlined } from '@ant-design/icons'
import { App, Button, Steps, Tooltip, Upload } from 'antd'
import { useState } from 'react'
import { Link, useLoaderData, useNavigate } from 'react-router'
import { api, API_MODE } from '../api'
import { StatusTag } from '../components/StatusTag'
import { HumanCheckTag } from '../components/Marks'
import { UploadMaterialButton } from '../components/UploadMaterialButton'
import { lookupResultLabel, materialKindLabel, sourceLabel } from '../labels'
import type { OALoaderData } from '../loaders'
import { isRunEnded, refreshRun } from '../runPoll'
import { useRunSnapshot } from '../useRunSnapshot'

const lineStyle = {
  display: 'flex',
  gap: 12,
  alignItems: 'center',
  flexWrap: 'wrap',
  padding: '12px 0',
  borderBottom: '1px solid var(--line-neutral-tertiary)',
} as const

// 새 사건 · 통지서 올리기 (PUpload 디자인). 올린 뒤에는 같은 화면에 머물고 주소만 ?oa=<oa_id>로 바뀐다.
// 그 주소의 loader가 OA·자료를 받아 오므로 새로고침해도 이어진다
export function UploadPage() {
  const data = useLoaderData() as OALoaderData | null
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [fileName, setFileName] = useState<string | null>(null)

  // 통지서 PDF를 올리면 사건·OA·실행을 만들고, 같은 화면에서 진행을 본다
  const upload = async (file: File) => {
    try {
      const created = await api.createCase(file)
      setFileName(file.name)
      navigate(`/cases/new?oa=${encodeURIComponent(created.oa_id)}`)
    } catch (e) {
      message.error(`올리지 못했습니다: ${e instanceof Error ? e.message : String(e)}`)
    }
    return false // antd가 따로 업로드하지 않게
  }

  return (
    <main
      style={{
        maxWidth: 1040,
        margin: '0 auto',
        padding: '32px 32px 80px',
        display: 'flex',
        flexDirection: 'column',
        gap: 32,
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <Link to="/cases" className="label2 t3">
          사건 목록
        </Link>
        <h1 className="heading1">새 사건 · 의견제출통지서 올리기</h1>
        <span className="body2 t2">
          통지서 PDF 하나만 올리면 나머지 자료는 출원번호로 찾아와요. 못 가져온 것만 올려 주시면 돼요.
        </span>
        {/* 자동 조회(#54)는 아직 없다: mock이 흉내라는 것을 숨기지 않는다 */}
        {API_MODE === 'mock' && <span className="label2 t3">mock: 예시 사건으로 흉내 내요</span>}
      </div>

      <Upload.Dragger accept="application/pdf,.pdf" showUploadList={false} beforeUpload={upload}>
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="body1" style={{ fontWeight: 600, margin: '8px 0 4px' }}>
          {fileName ? `${fileName} · 다른 파일을 올리면 새 사건이 만들어져요` : '의견제출통지서 PDF를 끌어 놓거나 눌러서 고르세요'}
        </p>
        <p className="label1 t3" style={{ margin: '0 0 8px' }}>
          공개·등록된 출원만 다뤄요. 미공개 출원과 실제 고객 사건은 올리지 마세요.
        </p>
      </Upload.Dragger>

      {data && <UploadProgress data={data} />}
    </main>
  )
}

// 올린 뒤: 왼쪽 "지금 하는 일"(실행 폴링) + 오른쪽 "찾아온 자료" + 정리부터 보기
function UploadProgress({ data }: { data: OALoaderData }) {
  const navigate = useNavigate()
  const { oaResult, materials, ready, oa } = data
  const { run, error: runError } = useRunSnapshot(oa.latest_run)
  const r = oaResult?.result ?? null
  const ended = isRunEnded(run.state)

  // 단계 위치는 "결과가 있나"로 정한다 (current_step은 자유 글이라 파싱하지 않고 아래 글로만 보인다).
  // 뒤 단계 결과가 있으면 앞 단계도 끝난 것
  const done = [r !== null || materials !== null, materials !== null, ready.summary, ready.compare, ready.directions]
  const doneCount = done.lastIndexOf(true) + 1
  const titles = ['통지서 읽기', '자료 찾아오기', '거절이유별 정리', '인용발명 대비 · 법률 근거', '대응 방향 후보']
  const detail: (string | undefined)[] = [
    r ? `출원번호·발송번호·거절이유 ${r.rejections.length}건` : undefined,
    materials ? `${materials.documents.length + materials.missing.length}건 중 ${materials.documents.length}건 가져옴` : undefined,
    ready.summary ? '끝남' : undefined,
    ready.compare ? '끝남' : undefined,
    ready.directions ? '끝남' : undefined,
  ]
  const items = titles.map((title, i) => {
    if (i < doneCount) return { title, description: detail[i] ?? '끝남' }
    // 지금 하는 단계: 서버가 준 current_step 글을 그대로 (실행이 멈췄으면 그 이유로 표시)
    if (i === doneCount && !ended) return { title, description: run.current_step ?? '진행 중' }
    if (i === doneCount && run.state === 'failed') return { title, description: run.current_step ?? '멈춤', status: 'error' as const }
    if (i === doneCount && run.state === 'cancelled') return { title, description: '취소됨' }
    return { title }
  })

  return (
    <>
      <section style={{ display: 'flex', gap: 40, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 260px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <h2 className="headline1">지금 하는 일</h2>
          <Steps direction="vertical" size="small" current={doneCount} items={items} />
          <span className="label2 t3">조회는 이 통지서 시점까지만 해요. 그 뒤 보정서·등록 청구항은 넣지 않아요.</span>
          {(!ended || runError !== null) && (
            <div className="label2 t3">
              {runError !== null && <span>상태를 받지 못했어요 · </span>}
              <Button type="link" size="small" onClick={() => void refreshRun(run.run_id)}>
                새로 보기
              </Button>
            </div>
          )}
        </div>

        <div style={{ flex: '2 1 480px', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
            <h2 className="headline1" style={{ flex: '1 1 auto' }}>
              찾아온 자료
            </h2>
            {/* 통지서에서 읽은 글자 그대로. 정리 결과가 있을 때만 */}
            {r && (
              <span className="label1 t3">
                출원번호 {r.application_number.raw_text ?? r.application_number.value ?? '모름'} · 발송번호{' '}
                {r.dispatch_number.raw_text ?? r.dispatch_number.value ?? '모름'}로 묶음
              </span>
            )}
          </div>
          {materials === null ? (
            // 목록이 아직 없으면 줄을 지어내지 않는다
            <span className="body2 t3" style={{ padding: '12px 0' }}>
              {ended ? '자료 목록을 받지 못했어요' : `자료 찾는 중: ${run.current_step ?? '준비 중'}`}
            </span>
          ) : (
            <>
              {materials.documents.map((d) => (
                <div key={d.document_id} style={lineStyle}>
                  <div style={{ flex: '1 1 260px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span className="body2" style={{ fontWeight: 600 }}>
                      {materialKindLabel[d.kind] ?? d.kind}
                    </span>
                    <span className="label1 t3">
                      {d.kind === 'oa' && r ? `발송번호 ${r.dispatch_number.raw_text ?? r.dispatch_number.value ?? '모름'} · ` : ''}
                      {sourceLabel[d.source] ?? d.source}
                    </span>
                  </div>
                  {/* 확인됨은 꼬리표 없음 */}
                  {d.status.value !== 'confirmed' && <StatusTag status={d.status} />}
                </div>
              ))}
              {materials.missing.map((x, i) => (
                <div key={`missing-${i}`} style={lineStyle}>
                  <div style={{ flex: '1 1 260px', display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span className="body2" style={{ fontWeight: 600 }}>
                      {x.what}
                    </span>
                    <span className="label1 t3">{lookupResultLabel[x.lookup_result]}</span>
                  </div>
                  {x.lookup_result === 'unsupported_country' ? (
                    <HumanCheckTag>직접 확인</HumanCheckTag>
                  ) : (
                    <StatusTag status={{ value: 'unverified', reason: x.lookup_result, checked: null, searched_scope: null }} />
                  )}
                  {x.ask_upload && (
                    <span style={{ display: 'inline-flex', gap: 8 }}>
                      {/* 다시 조회 API는 명세에 없어 누를 수 없다. 올리기는 서버 모드에서만 눌린다 */}
                      <Tooltip title="서버가 오면 다시 조회할 수 있어요">
                        <span>
                          <Button size="small" disabled>
                            다시 조회
                          </Button>
                        </span>
                      </Tooltip>
                      <UploadMaterialButton caseId={oa.case_id} />
                    </span>
                  )}
                </div>
              ))}
              {materials.documents.length + materials.missing.length === 0 && (
                <span className="body2 t3" style={{ padding: '12px 0' }}>
                  사건 자료가 아직 없어요
                </span>
              )}
            </>
          )}
        </div>
      </section>

      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', paddingTop: 8 }}>
        <span className="body2 t2" style={{ flex: '1 1 320px' }}>
          정리가 끝나면 바로 볼 수 있어요. 대비와 근거는 뒤에서 계속 돌아요.
        </span>
        <Button type="primary" size="large" disabled={!ready.summary} onClick={() => navigate(`/oas/${oa.oa_id}`)}>
          정리부터 보기
        </Button>
      </div>
    </>
  )
}
