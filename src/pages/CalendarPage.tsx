import { useMemo, useState } from 'react'
import FullCalendar from '@fullcalendar/react'
import dayGridPlugin from '@fullcalendar/daygrid'
import interactionPlugin from '@fullcalendar/interaction'
import { Alert, Space } from 'antd'
import { ApplicationDrawer } from '../components/application/ApplicationDrawer'
import { PageSection } from '../components/layout/PageSection'
import { useApplicationConflicts, useApplicationStore, useCalendarEvents } from '../store/useApplicationStore'
import type { JobApplication } from '../types/application'

export function CalendarPage() {
  const events = useCalendarEvents()
  const applications = useApplicationStore((state) => state.applications)
  const conflicts = useApplicationConflicts()
  const [currentApplication, setCurrentApplication] = useState<JobApplication>()
  const [drawerOpen, setDrawerOpen] = useState(false)

  const conflictSummary = useMemo(
    () => Array.from(new Set(conflicts.map((item) => `${item.companyName} ${item.round}`))).join('、'),
    [conflicts],
  )

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        showIcon
        type="info"
        message="日历集中查看面试、截止日期和 Offer 答复时间，也会突出英文面与冲突面试。"
      />
      {conflicts.length > 0 ? (
        <Alert showIcon type="error" message={`检测到面试时间冲突：${conflictSummary}`} />
      ) : null}
      <PageSection title="求职日历">
        <FullCalendar
          plugins={[dayGridPlugin, interactionPlugin]}
          initialView="dayGridMonth"
          locale="zh-cn"
          height="auto"
          events={events}
          eventTimeFormat={{ hour: '2-digit', minute: '2-digit', hour12: false }}
          eventClick={({ event }) => {
            const application = applications.find((item) => item.id === event.extendedProps.applicationId)
            if (!application) return
            setCurrentApplication(application)
            setDrawerOpen(true)
          }}
        />
      </PageSection>
      <ApplicationDrawer
        open={drawerOpen}
        mode="view"
        application={currentApplication}
        onClose={() => setDrawerOpen(false)}
        onSubmit={() => undefined}
      />
    </Space>
  )
}
