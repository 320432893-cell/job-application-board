import { BellOutlined } from '@ant-design/icons'
import { Alert, Button, List, Space, Switch, Tag, Typography } from 'antd'
import { useEffect } from 'react'
import { useApplicationStore, useNotificationPromptItems } from '../../store/useApplicationStore'

export function NotificationPanel() {
  const notificationSettings = useApplicationStore((state) => state.notificationSettings)
  const setNotificationEnabled = useApplicationStore((state) => state.setNotificationEnabled)
  const markNotificationSent = useApplicationStore((state) => state.markNotificationSent)
  const promptItems = useNotificationPromptItems()

  useEffect(() => {
    if (!notificationSettings.enabled || typeof window === 'undefined' || !('Notification' in window)) return
    if (Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [notificationSettings.enabled])

  useEffect(() => {
    if (!notificationSettings.enabled || typeof window === 'undefined' || !('Notification' in window)) return
    if (Notification.permission !== 'granted') return

    promptItems.forEach((item) => {
      new Notification(`${item.companyName} · ${item.title}`, {
        body: item.description,
      })
      markNotificationSent(item.id)
    })
  }, [notificationSettings.enabled, promptItems, markNotificationSent])

  return (
    <Space orientation="vertical" size={12} style={{ width: '100%' }}>
      <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}>
        <Typography.Title level={4} style={{ margin: 0 }}>
          浏览器提醒
        </Typography.Title>
        <Switch checked={notificationSettings.enabled} onChange={setNotificationEnabled} />
      </Space>
      <Alert
        showIcon
        type="info"
        icon={<BellOutlined />}
        title="开启后会为待办项发送一次浏览器提醒。"
      />
      {promptItems.length === 0 ? (
        <Typography.Text type="secondary">当前没有新的提醒待发送。</Typography.Text>
      ) : (
        <List
          dataSource={promptItems}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta title={`${item.companyName} · ${item.title}`} description={item.description} />
              <Tag>{item.type}</Tag>
            </List.Item>
          )}
        />
      )}
      <Button
        onClick={() => {
          if (typeof window !== 'undefined' && 'Notification' in window) {
            Notification.requestPermission()
          }
        }}
      >
        请求通知权限
      </Button>
    </Space>
  )
}
