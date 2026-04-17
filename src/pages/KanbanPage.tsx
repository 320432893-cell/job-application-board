import { DownloadOutlined, InboxOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { Alert, Button, Col, Empty, Popconfirm, Row, Select, Space, Statistic, Upload, message, type InputRef } from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as XLSX from 'xlsx'
import { ApplicationDrawer } from '../components/application/ApplicationDrawer'
import { QuickImportAssistant } from '../components/application/QuickImportAssistant'
import { SearchFilterBar } from '../components/application/SearchFilterBar'
import { KanbanBoard } from '../components/board/KanbanBoard'
import { PageSection } from '../components/layout/PageSection'
import { TodoPanel } from '../components/todo/TodoPanel'
import { NotificationPanel } from '../components/todo/NotificationPanel'
import { APPLICATION_STATUSES, type ApplicationStatus } from '../constants/status'
import { useApplicationConflicts, useApplicationStore, useFilteredApplications } from '../store/useApplicationStore'
import type { JobApplication } from '../types/application'

function exportApplications(applications: JobApplication[]) {
  const workbook = XLSX.utils.book_new()
  const worksheet = XLSX.utils.json_to_sheet(applications)
  XLSX.utils.book_append_sheet(workbook, worksheet, 'applications')
  XLSX.writeFile(workbook, 'job-application-board.xlsx')
}

export function KanbanPage() {
  const [messageApi, contextHolder] = message.useMessage()
  const initialize = useApplicationStore((state) => state.initialize)
  const applications = useApplicationStore((state) => state.applications)
  const searchKeyword = useApplicationStore((state) => state.searchKeyword)
  const filters = useApplicationStore((state) => state.filters)
  const setSearchKeyword = useApplicationStore((state) => state.setSearchKeyword)
  const setFilters = useApplicationStore((state) => state.setFilters)
  const resetFilters = useApplicationStore((state) => state.resetFilters)
  const loadMockData = useApplicationStore((state) => state.loadMockData)
  const createApplication = useApplicationStore((state) => state.createApplication)
  const updateApplication = useApplicationStore((state) => state.updateApplication)
  const deleteApplications = useApplicationStore((state) => state.deleteApplications)
  const updateApplicationStatus = useApplicationStore((state) => state.updateApplicationStatus)
  const updateApplicationsStatus = useApplicationStore((state) => state.updateApplicationsStatus)
  const replaceApplications = useApplicationStore((state) => state.replaceApplications)
  const selectedApplicationIds = useApplicationStore((state) => state.selectedApplicationIds)
  const setApplicationSelection = useApplicationStore((state) => state.setApplicationSelection)
  const clearApplicationSelection = useApplicationStore((state) => state.clearApplicationSelection)
  const filteredApplications = useFilteredApplications()
  const conflicts = useApplicationConflicts()

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerMode, setDrawerMode] = useState<'create' | 'view' | 'edit'>('create')
  const [currentApplication, setCurrentApplication] = useState<JobApplication>()
  const [quickImportOpen, setQuickImportOpen] = useState(false)
  const [draftApplication, setDraftApplication] = useState<Partial<JobApplication>>()
  const searchInputRef = useRef<InputRef | null>(null)

  useEffect(() => {
    initialize()
  }, [initialize])

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.ctrlKey && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        openDrawer('create')
      }
      if (event.ctrlKey && event.key.toLowerCase() === 'f') {
        event.preventDefault()
        searchInputRef.current?.focus()
      }
      if (event.key === 'Escape') {
        setDrawerOpen(false)
        clearApplicationSelection()
      }
      if (event.key === 'Delete' && selectedApplicationIds.length > 0) {
        handleBatchDelete()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedApplicationIds])

  const cities = useMemo(() => Array.from(new Set(applications.map((item) => item.city))), [applications])
  const offerCount = applications.filter((item) => item.offerReceived || item.status === 'Offer').length
  const interviewCount = applications.filter((item) => item.status === '面试中').length
  const urgentApplyCount = applications.filter(
    (item) => item.status === '待投递' && item.deadline && new Date(item.deadline).getTime() > Date.now() && (new Date(item.deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24) <= 3,
  ).length
  const todayInterviewCount = applications.filter((item) =>
    item.interviews.some((interview) => {
      const target = new Date(interview.date)
      const now = new Date()
      return target.toDateString() === now.toDateString()
    }),
  ).length
  const pendingOfferCount = applications.filter(
    (item) => item.offerReceived && item.offerDeadline && new Date(item.offerDeadline).getTime() > Date.now() && (new Date(item.offerDeadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24) <= 2,
  ).length

  function openDrawer(mode: 'create' | 'view' | 'edit', application?: JobApplication, initialValues?: Partial<JobApplication>) {
    setDrawerMode(mode)
    setCurrentApplication(application)
    setDraftApplication(initialValues)
    setDrawerOpen(true)
  }

  function handleSubmit(application: JobApplication) {
    if (drawerMode === 'edit') {
      updateApplication(application)
      messageApi.success('申请已更新')
      return
    }
    createApplication(application)
    messageApi.success('申请已创建')
  }

  function handleDelete(application: JobApplication) {
    deleteApplications([application.id])
    messageApi.success(`已删除 ${application.companyName}`)
  }

  function handleSelectAllVisible() {
    setApplicationSelection(filteredApplications.map((item) => item.id))
  }

  function handleBatchDelete() {
    deleteApplications(selectedApplicationIds)
    messageApi.success(`已删除 ${selectedApplicationIds.length} 条申请`)
  }

  function handleBatchStatusChange(status: ApplicationStatus) {
    updateApplicationsStatus(selectedApplicationIds, status)
    messageApi.success(`已批量更新为${status}`)
  }

  async function handleImport(file: File) {
    const buffer = await file.arrayBuffer()
    const workbook = XLSX.read(buffer)
    const firstSheet = workbook.Sheets[workbook.SheetNames[0]]
    const imported = XLSX.utils.sheet_to_json<JobApplication>(firstSheet)
    replaceApplications(imported)
    messageApi.success(`已导入 ${imported.length} 条申请`)
    return false
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      {contextHolder}
      <Alert
        type="info"
        showIcon
        message="支持更完整字段、筛选、导入导出和快捷操作。"
        description="可用快捷键：Ctrl+N 新建申请，Ctrl+F 聚焦搜索，ESC 关闭抽屉或清空选择。"
      />
      {conflicts.length > 0 ? (
        <Alert
          type="error"
          showIcon
          message={`检测到 ${conflicts.length} 个时间冲突，请优先处理时间撞车的申请`}
          description={conflicts
            .slice(0, 3)
            .map((item) =>
              item.kind === 'course'
                ? `${item.companyName} · ${item.round} 与课程 ${item.courseName} 冲突`
                : `${item.companyName} · ${item.round} 与其他面试冲突`,
            )
            .join('；')}
        />
      ) : null}

      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>
          <PageSection title="申请总数">
            <Statistic value={applications.length} suffix="条" />
          </PageSection>
        </Col>
        <Col xs={24} md={8}>
          <PageSection title="面试推进中">
            <Statistic value={interviewCount} suffix="家" />
          </PageSection>
        </Col>
        <Col xs={24} md={8}>
          <PageSection title="已拿 Offer">
            <Statistic value={offerCount} suffix="个" />
          </PageSection>
        </Col>
        <Col xs={24} md={8}>
          <PageSection title="3 天内待投递">
            <Statistic value={urgentApplyCount} suffix="条" />
          </PageSection>
        </Col>
        <Col xs={24} md={8}>
          <PageSection title="今日面试">
            <Statistic value={todayInterviewCount} suffix="场" />
          </PageSection>
        </Col>
        <Col xs={24} md={8}>
          <PageSection title="待答复 Offer">
            <Statistic value={pendingOfferCount} suffix="个" />
          </PageSection>
        </Col>
      </Row>

      <PageSection
        title="搜索与筛选"
        extra={
          <Space wrap>
            <Button onClick={() => loadMockData()}>重置示例数据</Button>
            <Button icon={<DownloadOutlined />} onClick={() => exportApplications(applications)}>
              导出 Excel
            </Button>
            <Upload beforeUpload={handleImport} showUploadList={false} accept=".xlsx,.xls,.csv">
              <Button icon={<InboxOutlined />}>导入 Excel/CSV</Button>
            </Upload>
            <Button icon={<ThunderboltOutlined />} onClick={() => setQuickImportOpen(true)}>
              快速录入助手
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openDrawer('create')}>
              新建申请
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <SearchFilterBar
            keyword={searchKeyword}
            filters={filters}
            cities={cities}
            onKeywordChange={setSearchKeyword}
            onFilterChange={setFilters}
            onReset={resetFilters}
            searchInputRef={searchInputRef}
          />
          <Space wrap>
            <Button onClick={handleSelectAllVisible}>全选当前结果</Button>
            <Button onClick={clearApplicationSelection}>清空选择</Button>
            <Select
              placeholder="批量改状态"
              style={{ width: 180 }}
              value={undefined}
              options={APPLICATION_STATUSES.map((item) => ({ label: item, value: item }))}
              onChange={(value) => {
                if (value) {
                  handleBatchStatusChange(value)
                }
              }}
              disabled={selectedApplicationIds.length === 0}
            />
            <Popconfirm title="确认删除选中的申请吗？" onConfirm={handleBatchDelete}>
              <Button danger disabled={selectedApplicationIds.length === 0}>
                批量删除
              </Button>
            </Popconfirm>
            <span>已选 {selectedApplicationIds.length} 条</span>
          </Space>
        </Space>
      </PageSection>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <PageSection title="今日待办">
            <TodoPanel />
          </PageSection>
        </Col>
        <Col xs={24} lg={10}>
          <PageSection title="提醒设置">
            <NotificationPanel />
          </PageSection>
        </Col>
      </Row>

      <PageSection title="申请看板">
        {filteredApplications.length === 0 ? (
          <Empty description="暂无匹配申请，试试清空筛选或添加第一条申请" />
        ) : (
          <KanbanBoard
            onView={(application) => openDrawer('view', application)}
            onEdit={(application) => openDrawer('edit', application)}
            onDelete={handleDelete}
            onStatusChange={(id, status) => {
              updateApplicationStatus(id, status)
              messageApi.success(`状态已更新为${status}`)
            }}
          />
        )}
      </PageSection>

      <QuickImportAssistant
        open={quickImportOpen}
        onClose={() => setQuickImportOpen(false)}
        onApply={(application) => {
          setQuickImportOpen(false)
          openDrawer('create', undefined, application)
        }}
      />
      <ApplicationDrawer
        open={drawerOpen}
        mode={drawerMode}
        application={currentApplication}
        initialValues={draftApplication}
        onClose={() => {
          setDrawerOpen(false)
          setDraftApplication(undefined)
        }}
        onSubmit={handleSubmit}
      />
    </Space>
  )
}
