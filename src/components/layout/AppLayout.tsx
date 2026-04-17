import { Layout, Typography } from 'antd'
import type { PropsWithChildren, ReactNode } from 'react'

interface AppLayoutProps extends PropsWithChildren {
  sidebar: ReactNode
  title: string
  subtitle: string
}

export function AppLayout({ sidebar, title, subtitle, children }: AppLayoutProps) {
  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Layout.Sider width={240} theme="light" breakpoint="lg" collapsedWidth={80}>
        {sidebar}
      </Layout.Sider>
      <Layout>
        <Layout.Header className="app-header">
          <div>
            <Typography.Title level={3} style={{ margin: 0 }}>
              {title}
            </Typography.Title>
            <Typography.Text type="secondary">{subtitle}</Typography.Text>
          </div>
        </Layout.Header>
        <Layout.Content className="app-content">{children}</Layout.Content>
      </Layout>
    </Layout>
  )
}
