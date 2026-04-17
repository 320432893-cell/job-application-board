import { DeleteOutlined, EditOutlined, EyeOutlined } from '@ant-design/icons'
import { Badge, Button, Card, Checkbox, Popconfirm, Space, Tag, Typography } from 'antd'
import dayjs from 'dayjs'
import { useApplicationStore, useConflictApplicationIds } from '../../store/useApplicationStore'
import type { JobApplication } from '../../types/application'
import { isToday, isWithinDays } from '../../utils/date'

interface ApplicationCardProps {
  application: JobApplication
  onView: (application: JobApplication) => void
  onEdit: (application: JobApplication) => void
  onDelete: (application: JobApplication) => void
}

export function ApplicationCard({ application, onView, onEdit, onDelete }: ApplicationCardProps) {
  const searchKeyword = useApplicationStore((state) => state.searchKeyword)
  const selectedApplicationIds = useApplicationStore((state) => state.selectedApplicationIds)
  const toggleApplicationSelection = useApplicationStore((state) => state.toggleApplicationSelection)
  const conflictApplicationIds = useConflictApplicationIds()
  const isSelected = selectedApplicationIds.includes(application.id)
  const hasConflict = conflictApplicationIds.includes(application.id)
  const hasEnglishInterview = application.interviews.some((item) => item.language === '英文')
  const hasOfflineInterview = application.interviews.some((item) => item.format === '线下')

  return (
    <Badge.Ribbon text={application.status} color={getRibbonColor(application.status)}>
      <Card size="small" className="application-card">
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Space align="start" style={{ width: '100%', justifyContent: 'space-between' }}>
            <div>
              <Typography.Title level={5} style={{ margin: 0 }}>
                {renderHighlightedText(application.companyName, searchKeyword)}
              </Typography.Title>
              <Typography.Text type="secondary">{renderHighlightedText(application.position, searchKeyword)}</Typography.Text>
            </div>
            <Checkbox checked={isSelected} onChange={() => toggleApplicationSelection(application.id)} />
          </Space>

          <Space size={[4, 8]} wrap>
            <Tag>{renderHighlightedText(application.city, searchKeyword)}</Tag>
            <Tag>{application.companyType}</Tag>
            <Tag>{application.jobType}</Tag>
            {application.industry ? <Tag>{application.industry}</Tag> : null}
            {application.status === '待投递' && isWithinDays(application.deadline, 3) ? <Tag color="red">截止临近</Tag> : null}
            {application.interviews.some((item) => isToday(item.date)) ? <Tag color="blue">今天面试</Tag> : null}
            {application.offerReceived && isWithinDays(application.offerDeadline, 2) ? <Tag color="green">待答复 Offer</Tag> : null}
            {hasEnglishInterview ? <Tag color="purple">英语面</Tag> : null}
            {hasOfflineInterview ? <Tag color="volcano">线下面</Tag> : null}
            {hasConflict ? <Tag color="red">面试冲突</Tag> : null}
          </Space>

          <Typography.Text>薪资：{application.offerDetails?.salary || application.salary || '待确认'}</Typography.Text>
          <Typography.Text>出勤：{application.workDays || '待确认'}</Typography.Text>
          <Typography.Text>
            截止：{application.deadline ? dayjs(application.deadline).format('MM-DD HH:mm') : '未设置'}
          </Typography.Text>

          <Space>
            <Button size="small" icon={<EyeOutlined />} onClick={() => onView(application)}>
              详情
            </Button>
            <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(application)}>
              编辑
            </Button>
            <Popconfirm title="确认删除这条申请吗？" onConfirm={() => onDelete(application)}>
              <Button size="small" danger icon={<DeleteOutlined />}>
                删除
              </Button>
            </Popconfirm>
          </Space>
        </Space>
      </Card>
    </Badge.Ribbon>
  )
}

function renderHighlightedText(text: string | undefined, keyword: string) {
  if (!text) return ''
  const normalizedKeyword = keyword.trim()
  if (!normalizedKeyword) return text

  const lowerText = text.toLowerCase()
  const lowerKeyword = normalizedKeyword.toLowerCase()
  const startIndex = lowerText.indexOf(lowerKeyword)

  if (startIndex === -1) return text

  const endIndex = startIndex + normalizedKeyword.length

  return (
    <>
      {text.slice(0, startIndex)}
      <mark>{text.slice(startIndex, endIndex)}</mark>
      {text.slice(endIndex)}
    </>
  )
}

function getRibbonColor(status: JobApplication['status']) {
  switch (status) {
    case '已投递':
      return 'blue'
    case '笔试':
      return 'purple'
    case '面试中':
      return 'orange'
    case 'Offer':
      return 'green'
    case '已拒绝':
      return 'red'
    default:
      return 'default'
  }
}
