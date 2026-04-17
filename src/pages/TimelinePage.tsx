import { Card, Col, Row, Statistic, Table, Tag, Timeline } from 'antd'
import dayjs from 'dayjs'
import { useApplicationStore } from '../store/useApplicationStore'

export function TimelinePage() {
  const applications = useApplicationStore((state) => state.applications)

  return (
    <Row gutter={[16, 16]}>
      {applications.map((application) => (
        <Col span={24} key={application.id}>
          <Card title={`${application.companyName} · ${application.position}`}>
            <Timeline
              items={[
                { color: 'blue', children: `投递：${application.applyDate ? dayjs(application.applyDate).format('YYYY-MM-DD HH:mm') : '未投递'}` },
                { color: 'purple', children: `当前状态：${application.status}` },
                ...application.interviews.map((interview) => ({
                  color: interview.result === '未通过' ? 'red' : 'green',
                  children: `${interview.round} · ${dayjs(interview.date).format('YYYY-MM-DD HH:mm')} · ${interview.result || '等待中'}`,
                })),
                application.offerReceived
                  ? { color: 'green', children: `Offer 答复截止：${application.offerDeadline ? dayjs(application.offerDeadline).format('YYYY-MM-DD HH:mm') : '未设置'}` }
                  : { color: 'gray', children: '暂无 Offer' },
              ]}
            />
          </Card>
        </Col>
      ))}
    </Row>
  )
}

export function StatsPage() {
  const applications = useApplicationStore((state) => state.applications)

  const byStatus = applications.reduce<Record<string, number>>((result, item) => {
    result[item.status] = (result[item.status] || 0) + 1
    return result
  }, {})

  const byCity = applications.reduce<Record<string, number>>((result, item) => {
    result[item.city] = (result[item.city] || 0) + 1
    return result
  }, {})

  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={8}>
        <Card>
          <Statistic title="申请总数" value={applications.length} />
        </Card>
      </Col>
      <Col xs={24} md={8}>
        <Card>
          <Statistic title="Offer 数量" value={applications.filter((item) => item.offerReceived).length} />
        </Card>
      </Col>
      <Col xs={24} md={8}>
        <Card>
          <Statistic title="可转正岗位" value={applications.filter((item) => item.canConvert).length} />
        </Card>
      </Col>
      <Col span={24}>
        <Card title="状态分布">
          <Table
            pagination={false}
            rowKey="status"
            dataSource={Object.entries(byStatus).map(([status, count]) => ({ status, count }))}
            columns={[
              { title: '状态', dataIndex: 'status', render: (value) => <Tag>{value}</Tag> },
              { title: '数量', dataIndex: 'count' },
            ]}
          />
        </Card>
      </Col>
      <Col span={24}>
        <Card title="城市分布">
          <Table
            pagination={false}
            rowKey="city"
            dataSource={Object.entries(byCity).map(([city, count]) => ({ city, count }))}
            columns={[
              { title: '城市', dataIndex: 'city' },
              { title: '数量', dataIndex: 'count' },
            ]}
          />
        </Card>
      </Col>
    </Row>
  )
}
