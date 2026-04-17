import { RadarChartOutlined } from '@ant-design/icons'
import { Card } from 'antd'
import { PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { JobApplication } from '../../types/application'

interface OfferRadarChartProps {
  data: JobApplication[]
  weights: {
    salary: number
    development: number
    location: number
    brand: number
    workload: number
  }
}

const dimensions = [
  { key: 'salary', label: '薪资' },
  { key: 'development', label: '发展前景' },
  { key: 'location', label: '地点' },
  { key: 'brand', label: '公司品牌' },
  { key: 'workload', label: '工作强度' },
] as const

export function OfferRadarChart({ data, weights }: OfferRadarChartProps) {
  const chartData = dimensions.map((dimension) => {
    const row: Record<string, number | string> = { subject: dimension.label }
    data.forEach((item) => {
      const score = item.decisionScores[dimension.key]
      row[item.id] = score * weights[dimension.key]
    })
    return row
  })

  return (
    <Card title="Offer 决策雷达图" extra={<RadarChartOutlined />}>
      <div style={{ width: '100%', height: 360 }}>
        <ResponsiveContainer>
          <RadarChart data={chartData}>
            <PolarGrid />
            <PolarAngleAxis dataKey="subject" />
            <Tooltip />
            {data.map((item, index) => (
              <Radar
                key={item.id}
                name={item.companyName}
                dataKey={item.id}
                stroke={['#1677ff', '#52c41a', '#faad14', '#722ed1'][index % 4]}
                fill={['#1677ff', '#52c41a', '#faad14', '#722ed1'][index % 4]}
                fillOpacity={0.15}
              />
            ))}
          </RadarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  )
}
