import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { Empty, Typography } from 'antd'
import type { JobApplication } from '../../types/application'
import { ApplicationCard } from './ApplicationCard'

interface KanbanColumnProps {
  title: string
  items: JobApplication[]
  onView: (application: JobApplication) => void
  onEdit: (application: JobApplication) => void
  onDelete: (application: JobApplication) => void
}

export function KanbanColumn({ title, items, onView, onEdit, onDelete }: KanbanColumnProps) {
  return (
    <div className="kanban-column">
      <div className="kanban-column-header">
        <Typography.Title level={5} style={{ margin: 0 }}>
          {title}
        </Typography.Title>
        <Typography.Text type="secondary">{items.length} 项</Typography.Text>
      </div>

      <SortableContext items={items.map((item) => item.id)} strategy={verticalListSortingStrategy}>
        <div className="kanban-column-body">
          {items.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无申请" />
          ) : (
            items.map((application) => (
              <ApplicationCard
                key={application.id}
                application={application}
                onView={onView}
                onEdit={onEdit}
                onDelete={onDelete}
              />
            ))
          )}
        </div>
      </SortableContext>
    </div>
  )
}
