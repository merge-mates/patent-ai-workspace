import { UploadOutlined } from '@ant-design/icons'
import { App, Button, Tooltip, Upload } from 'antd'
import { useRevalidator } from 'react-router'
import { api, API_MODE } from '../api'

// "올려 주세요": 조회하지 못한 자료를 올린다 (POST /cases/{id}/documents).
// what = 이 버튼이 답하는 빠진 자료 (missing[].what 글자 그대로). 서버가 이 글자로 빠진 자료를 찾는다.
// 서버 모드에서만 눌린다. mock은 파일을 읽지 않아 지어내지 않고 막아 둔다 (api.uploadDocument도 오류를 던진다)
// label: 버튼 글자 (자료 줄은 "올려 주세요", 직접 할 일은 "올리기")
export function UploadMaterialButton({ caseId, what, label = '올려 주세요' }: { caseId: string; what: string; label?: string }) {
  const { message } = App.useApp()
  const revalidator = useRevalidator()

  // 올린 뒤 loader를 다시 불러 사건 자료 목록을 새로 받는다
  const upload = async (file: File) => {
    try {
      await api.uploadDocument(caseId, file, what)
      message.success(`${file.name}을(를) 올렸어요`)
      await revalidator.revalidate()
    } catch (e) {
      message.error(`올리지 못했습니다: ${e instanceof Error ? e.message : String(e)}`)
    }
    return false // antd가 따로 업로드하지 않게
  }

  if (API_MODE === 'mock') {
    return (
      <Tooltip title="mock에서는 올릴 수 없어요. 서버가 오면 올릴 수 있어요">
        <span>
          <Button size="small" icon={<UploadOutlined />} disabled>
            {label}
          </Button>
        </span>
      </Tooltip>
    )
  }
  return (
    <Upload accept=".pdf,application/pdf" showUploadList={false} beforeUpload={upload}>
      <Button size="small" icon={<UploadOutlined />}>
        {label}
      </Button>
    </Upload>
  )
}
