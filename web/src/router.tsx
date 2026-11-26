import { createBrowserRouter, redirect } from 'react-router'
import { ResultGate } from './components/ResultGate'
import { AppShell } from './layout/AppShell'
import { CaseShell } from './layout/CaseShell'
import { caseLoader, casesLoader, compareLoader, directionsLoader, draftsLoader, oaLoader, uploadLoader } from './loaders'
import { CaseListPage } from './pages/CaseListPage'
import { ComparePage } from './pages/compare/ComparePage'
import { DirectionsPage } from './pages/directions/DirectionsPage'
import { DraftsPage } from './pages/drafts/DraftsPage'
import { LegalPage } from './pages/legal/LegalPage'
import { UploadPage } from './pages/UploadPage'
import { RouteError } from './pages/RouteError'
import { WorkbenchPage } from './pages/workbench/WorkbenchPage'

// 화면 경로. 데이터는 각 경로의 loader가 미리 받는다
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <RouteError />,
    // 주소로 바로 들어와 처음 데이터를 받는 동안 빈 흰 화면 대신 알림 (화면 안 이동은 AppShell이 알린다)
    hydrateFallbackElement: (
      <div className="body1 t3" style={{ padding: 48, textAlign: 'center' }}>
        사건 자료를 불러오는 중이에요…
      </div>
    ),
    children: [
      { index: true, loader: () => redirect('/cases') },
      { path: 'cases', loader: casesLoader, element: <CaseListPage />, errorElement: <RouteError /> },
      { path: 'cases/new', loader: uploadLoader, element: <UploadPage />, errorElement: <RouteError /> },
      { path: 'legal', element: <LegalPage /> },
      { path: 'cases/:caseId', loader: caseLoader, errorElement: <RouteError /> },
      {
        id: 'oa',
        path: 'oas/:oaId',
        loader: oaLoader,
        element: <CaseShell />,
        errorElement: <RouteError />,
        children: [
          { index: true, element: <WorkbenchPage /> },
          { path: 'compare', loader: compareLoader, element: <ComparePage />, errorElement: <RouteError /> },
          { path: 'directions', loader: directionsLoader, element: <ResultGate><DirectionsPage /></ResultGate>, errorElement: <RouteError /> },
          { path: 'drafts', loader: draftsLoader, element: <ResultGate><DraftsPage /></ResultGate>, errorElement: <RouteError /> },
        ],
      },
    ],
  },
])
