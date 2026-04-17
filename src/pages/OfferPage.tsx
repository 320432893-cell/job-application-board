import { Alert, Checkbox, Empty, Space, Typography } from 'antd'
import { useOfferApplications } from '../store/useApplicationStore'
import { OfferComparisonTable } from '../components/offer/OfferComparisonTable'
import { OfferRadarChart } from '../components/offer/OfferRadarChart'
import { useMemo, useState } from 'react'
import { InputNumber } from 'antd'
import { useApplicationStore } from '../store/useApplicationStore'

export function OfferPage() {
  const offers = useOfferApplications()
  const selectedOfferIds = useApplicationStore((state) => state.selectedOfferIds)
  const toggleOfferSelection = useApplicationStore((state) => state.toggleOfferSelection)
  const [weights, setWeights] = useState({ salary: 1, development: 1, location: 1, brand: 1, workload: 1 })

  const selectedOffers = offers.filter((item) => selectedOfferIds.includes(item.id))
  const displayOffers = selectedOffers.length > 0 ? selectedOffers : offers

  const scoreSummary = useMemo(
    () =>
      displayOffers.map((item) => ({
        id: item.id,
        companyName: item.companyName,
        total:
          item.decisionScores.salary * weights.salary +
          item.decisionScores.development * weights.development +
          item.decisionScores.location * weights.location +
          item.decisionScores.brand * weights.brand +
          item.decisionScores.workload * weights.workload,
      })),
    [displayOffers, weights],
  )

  return (
    <Space orientation="vertical" size={16} style={{ width: '100%' }}>
      <Alert
        showIcon
        type="success"
        title="先用表格对比基础信息，再用雷达图和加权得分辅助判断 Offer 去向。"
      />

      <div>
        <Typography.Title level={4}>选择要对比的 Offer</Typography.Title>
        {offers.length === 0 ? (
          <Empty description="暂无 Offer 数据" />
        ) : (
          <Space wrap>
            {offers.map((offer) => (
              <Checkbox
                key={offer.id}
                checked={selectedOfferIds.includes(offer.id)}
                onChange={() => toggleOfferSelection(offer.id)}
              >
                {offer.companyName} · {offer.position}
              </Checkbox>
            ))}
          </Space>
        )}
      </div>

      <div>
        <Typography.Title level={4}>权重设置</Typography.Title>
        <Space wrap>
          <InputNumber min={0} max={5} addonBefore="薪资" value={weights.salary} onChange={(value) => setWeights((prev) => ({ ...prev, salary: value ?? 1 }))} />
          <InputNumber min={0} max={5} addonBefore="发展" value={weights.development} onChange={(value) => setWeights((prev) => ({ ...prev, development: value ?? 1 }))} />
          <InputNumber min={0} max={5} addonBefore="地点" value={weights.location} onChange={(value) => setWeights((prev) => ({ ...prev, location: value ?? 1 }))} />
          <InputNumber min={0} max={5} addonBefore="品牌" value={weights.brand} onChange={(value) => setWeights((prev) => ({ ...prev, brand: value ?? 1 }))} />
          <InputNumber min={0} max={5} addonBefore="强度" value={weights.workload} onChange={(value) => setWeights((prev) => ({ ...prev, workload: value ?? 1 }))} />
        </Space>
      </div>

      <Typography.Title level={4}>综合得分</Typography.Title>
      <Space wrap>
        {scoreSummary.map((item) => (
          <Alert key={item.id} type="info" message={`${item.companyName}：${item.total.toFixed(1)} 分`} />
        ))}
      </Space>

      <Typography.Title level={4}>对比表</Typography.Title>
      <OfferComparisonTable data={displayOffers} />
      <OfferRadarChart data={displayOffers} weights={weights} />
    </Space>
  )
}
