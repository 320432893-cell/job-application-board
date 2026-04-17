import { Alert, List, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useTodoItems } from '../../store/useApplicationStore'

export function TodoPanel() {
  const items = useTodoItems()

  return (
    <div>
      <Typography.Title level={4}>今日待办</Typography.Title>
      <Typography.Paragraph type="secondary" style={{ marginTop: -8 }}>
        把投递截止、面试安排、Offer 答复和面试准备提醒集中展示，减少遗漏。
      </Typography.Paragraph>
      {items.length === 0 ? (
        <Alert type="success" showIcon message="今天没有高优先级待办，可以继续处理其他申请。" />
      ) : (
        <List
          bordered
          dataSource={items}
          renderItem={(item) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <Typography.Text strong>
                    {item.companyName} · {item.title}
                  </Typography.Text>
                }
                description={`${item.description} · ${dayjs(item.date).format('MM-DD HH:mm')}`}
              />
              <Tag color={getTagColor(item.type)}>{getTagText(item.type)}</Tag>
            </List.Item>
          )}
        />
      )}
    </div>
  )
}

function getTagColor(type: 'interview' | 'deadline' | 'offer' | 'reminder') {
  if (type === 'interview') return 'blue'
  if (type === 'deadline') return 'red'
  if (type === 'offer') return 'green'
  return 'purple'
}

function getTagText(type: 'interview' | 'deadline' | 'offer' | 'reminder') {
  if (type === 'interview') return '面试'
  if (type === 'deadline') return '截止'
  if (type === 'offer') return 'Offer'
  return '提醒'
}
