import './App.css'
import { AppLayout } from './components/layout/AppLayout'
import { SidebarNav } from './components/layout/SidebarNav'
import { AppRouter } from './router'

function App() {
  return (
    <AppLayout
      sidebar={<SidebarNav />}
      title="用看板管理求职全流程"
      subtitle="聚焦今日待办、进度推进和 Offer 决策"
    >
      <AppRouter />
    </AppLayout>
  )
}

export default App
