import { Card, Typography } from 'antd'
import type { PropsWithChildren } from 'react'

interface PageSectionProps extends PropsWithChildren {
  title: string
  extra?: React.ReactNode
}

export function PageSection({ title, extra, children }: PageSectionProps) {
  return (
    <Card
      title={<Typography.Text strong>{title}</Typography.Text>}
      extra={extra}
      className="page-section"
    >
      {children}
    </Card>
  )
}
