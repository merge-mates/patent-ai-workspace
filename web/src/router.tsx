import { createBrowserRouter, redirect } from 'react-router'
import { AppShell } from './layout/AppShell'
import { casesLoader } from './loaders'
import { CaseListPage } from './pages/CaseListPage'
import { RouteError } from './pages/RouteError'

// 화면 경로. 데이터는 각 경로의 loader가 미리 받는다
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    errorElement: <RouteError />,
    children: [
      { index: true, loader: () => redirect('/cases') },
      { path: 'cases', loader: casesLoader, element: <CaseListPage />, errorElement: <RouteError /> },
    ],
  },
])
