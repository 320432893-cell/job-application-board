import { Route, Routes } from 'react-router-dom'
import { CalendarPage } from '../pages/CalendarPage'
import { KanbanPage } from '../pages/KanbanPage'
import { OfferPage } from '../pages/OfferPage'
import { StatsPage, TimelinePage } from '../pages/TimelinePage'

export function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<KanbanPage />} />
      <Route path="/calendar" element={<CalendarPage />} />
      <Route path="/timeline" element={<TimelinePage />} />
      <Route path="/offers" element={<OfferPage />} />
      <Route path="/stats" element={<StatsPage />} />
    </Routes>
  )
}
