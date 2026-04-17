import {
  CalendarOutlined,
  AppstoreOutlined,
  BarChartOutlined,
  NodeIndexOutlined,
  TrophyOutlined,
} from '@ant-design/icons'
import { Menu, Typography } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'

const menuItems = [
  { key: '/', icon: <AppstoreOutlined />, label: '求职看板' },
  { key: '/calendar', icon: <CalendarOutlined />, label: '日历视图' },
  { key: '/timeline', icon: <NodeIndexOutlined />, label: '时间线' },
  { key: '/stats', icon: <BarChartOutlined />, label: '数据统计' },
  { key: '/offers', icon: <TrophyOutlined />, label: 'Offer 对比' },
]

export function SidebarNav() {
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <div>
      <div className="app-logo">
        <Typography.Title level={4} style={{ margin: 0, color: '#1677ff' }}>
          求职申请管理看板
        </Typography.Title>
        <Typography.Text type="secondary">林震作品</Typography.Text>
      </div>
      <Menu
        mode="inline"
        selectedKeys={[location.pathname]}
        items={menuItems}
        onClick={({ key }) => navigate(key)}
        style={{ borderInlineEnd: 'none' }}
      />
    </div>
  )
}
