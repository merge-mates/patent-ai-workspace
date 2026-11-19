import { createBrowserRouter, redirect } from 'react-router'
import { AppShell } from './layout/AppShell'
import { CaseShell } from './layout/CaseShell'
import { caseLoader, casesLoader, compareLoader, oaLoader } from './loaders'
import { CaseListPage } from './pages/CaseListPage'
import { ComparePage } from './pages/compare/ComparePage'
import { LegalPage } from './pages/legal/LegalPage'
import { RouteError } from './pages/RouteError'
import { WorkbenchPage } from './pages/workbench/WorkbenchPage'

// 화면 경로. 데이터는 각 경로의 loader가 미리 받는다
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, loader: () => redirect('/cases') },
      { path: 'cases', loader: casesLoader, element: <CaseListPage />, errorElement: <RouteError /> },
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
        ],
      },
    ],
  },
])
