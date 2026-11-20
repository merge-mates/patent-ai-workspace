import { InboxOutlined } from '@ant-design/icons'
import { App, Upload } from 'antd'
import { useNavigate } from 'react-router'
import { api, API_MODE } from '../api'

// 새 사건 · 통지서 올리기 (모양은 다음 task에서 PUpload 디자인대로 채운다)
export function UploadPage() {
  const navigate = useNavigate()
  const { message } = App.useApp()

  // 통지서 PDF를 올리면 사건·OA를 만들고 작업대로 간다 (mock은 예시 사건을 연다)
  const upload = async (file: File) => {
    try {
      const created = await api.createCase(file)
      message.success(
        API_MODE === 'mock' ? `${file.name}: mock이라 예시 사건을 엽니다` : `${file.name}을 올렸습니다`,
      )
      navigate(`/oas/${created.oa_id}`)
    } catch (e) {
      message.error(`올리지 못했습니다: ${e instanceof Error ? e.message : String(e)}`)
    }
    return false // antd가 따로 업로드하지 않게
  }

  return (
    <main style={{ maxWidth: 720, margin: '0 auto', padding: '40px 32px 80px', display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <h1 className="heading1">새 사건 · 의견제출통지서 올리기</h1>
        <span className="body2 t2">
          새 사건을 만들고 거절이유별로 정리합니다. 같은 사건의 다음 통지서는 사건 안에서 올립니다.
        </span>
      </div>
      <Upload.Dragger accept="application/pdf,.pdf" showUploadList={false} beforeUpload={upload}>
        <p className="ant-upload-drag-icon">
          <InboxOutlined />
        </p>
        <p className="ant-upload-text">의견제출통지서 PDF 올리기</p>
      </Upload.Dragger>
    </main>
  )
}
