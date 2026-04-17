import { DndContext, PointerSensor, closestCorners, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core'
import { useApplicationsByStatus } from '../../store/useApplicationStore'
import type { JobApplication } from '../../types/application'
import { KanbanColumn } from './KanbanColumn'

interface KanbanBoardProps {
  onView: (application: JobApplication) => void
  onEdit: (application: JobApplication) => void
  onDelete: (application: JobApplication) => void
  onStatusChange: (id: string, status: JobApplication['status']) => void
}

export function KanbanBoard({ onView, onEdit, onDelete, onStatusChange }: KanbanBoardProps) {
  const groups = useApplicationsByStatus()
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))

  function handleDragEnd(event: DragEndEvent) {
    const activeId = String(event.active.id)
    const overId = event.over ? String(event.over.id) : ''
    if (!overId) return

    const targetStatus = groups.find((group) => group.status === overId)?.status
    if (targetStatus) {
      onStatusChange(activeId, targetStatus)
    }
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCorners} onDragEnd={handleDragEnd}>
      <div className="kanban-board">
        {groups.map((group) => (
          <div key={group.status} id={group.status}>
            <KanbanColumn
              title={group.status}
              items={group.items}
              onView={onView}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          </div>
        ))}
      </div>
    </DndContext>
  )
}
