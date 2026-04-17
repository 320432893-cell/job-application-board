import { Table, Tag } from 'antd'
import dayjs from 'dayjs'
import type { JobApplication } from '../../types/application'

interface OfferComparisonTableProps {
  data: JobApplication[]
}

export function OfferComparisonTable({ data }: OfferComparisonTableProps) {
  return (
    <Table
      rowKey="id"
      dataSource={data}
      pagination={false}
      columns={[
        { title: '公司', dataIndex: 'companyName' },
        { title: '岗位', dataIndex: 'position' },
        { title: '城市', dataIndex: 'city' },
        { title: '公司类型', dataIndex: 'companyType', render: (value) => <Tag>{value}</Tag> },
        { title: '招聘类型', dataIndex: 'jobType' },
        { title: '薪资', render: (_, item) => item.offerDetails?.salary || item.salary || '待确认' },
        { title: '出勤', dataIndex: 'workDays', render: (value) => value || '待确认' },
        { title: '可转正', dataIndex: 'canConvert', render: (value) => (value ? '是' : '否') },
        { title: '福利', render: (_, item) => item.offerDetails?.benefits || '待确认' },
        {
          title: '入职时间',
          render: (_, item) =>
            item.offerDetails?.startDate ? dayjs(item.offerDetails.startDate).format('YYYY-MM-DD') : '未设置',
        },
        {
          title: '答复截止',
          dataIndex: 'offerDeadline',
          render: (value) => (value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '未设置'),
        },
      ]}
    />
  )
}
