import { BulbOutlined } from '@ant-design/icons'
import { Alert, Button, Drawer, Input, Space, Typography } from 'antd'
import { nanoid } from 'nanoid'
import { useMemo, useState } from 'react'
import type { JobApplication } from '../../types/application'

interface QuickImportAssistantProps {
  open: boolean
  onClose: () => void
  onApply: (application: Partial<JobApplication>) => void
}

const cityCandidates = ['北京', '上海', '广州', '深圳', '杭州', '成都', '南京', '苏州', '武汉', '西安']
const companyTypeRules = [
  { pattern: /外企|foreign|global|英文/i, value: '外企' as const },
  { pattern: /大厂|阿里|腾讯|字节|美团|京东|百度/i, value: '大厂' as const },
  { pattern: /独角兽/i, value: '独角兽' as const },
  { pattern: /创业/i, value: '创业公司' as const },
  { pattern: /传统企业|制造|银行/i, value: '传统企业' as const },
]
const jobTypeRules = [
  { pattern: /暑期实习/i, value: '暑期实习' as const },
  { pattern: /日常实习|实习生/i, value: '日常实习' as const },
  { pattern: /校招|应届|全职/i, value: '校招全职' as const },
]
const industryRules = [
  { pattern: /互联网|产品|运营|算法|开发/i, value: '互联网' as const },
  { pattern: /金融|证券|银行|基金/i, value: '金融' as const },
  { pattern: /制造|工厂|供应链/i, value: '制造' as const },
  { pattern: /咨询/i, value: '咨询' as const },
  { pattern: /教育/i, value: '教育' as const },
  { pattern: /快消|消费|零售/i, value: '消费' as const },
  { pattern: /医疗|医药|生物/i, value: '医疗' as const },
]
const positionRules = ['产品经理', '产品运营', '数据分析', '商业分析', '项目经理', '运营', '市场', '销售']
const techKeywordRules = [
  /sql/i,
  /python/i,
  /excel/i,
  /power bi/i,
  /tableau/i,
  /figma/i,
  /axure/i,
  /java/i,
  /c\+\+/i,
  /react/i,
]
const techKeywordLabels = ['SQL', 'Python', 'Excel', 'Power BI', 'Tableau', 'Figma', 'Axure', 'Java', 'C++', 'React']

export function QuickImportAssistant({ open, onClose, onApply }: QuickImportAssistantProps) {
  const [sourceText, setSourceText] = useState('')

  const parsed = useMemo(() => parseJobDescription(sourceText), [sourceText])

  return (
    <Drawer
      open={open}
      width={560}
      title="快速录入助手"
      onClose={onClose}
      destroyOnClose
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" disabled={!sourceText.trim()} onClick={() => onApply(parsed)}>
            回填到表单
          </Button>
        </Space>
      }
    >
      <Space orientation="vertical" size={16} style={{ width: '100%' }}>
        <Alert
          showIcon
          type="info"
          icon={<BulbOutlined />}
          title="粘贴 JD 文本或职位描述，助手会提取公司、岗位、城市、薪资、招聘类型和技能要求。"
        />
        <Input.TextArea
          rows={12}
          placeholder="把 JD 文本粘贴到这里"
          value={sourceText}
          onChange={(event) => setSourceText(event.target.value)}
        />
        <div>
          <Typography.Title level={5}>解析预览</Typography.Title>
          <Space orientation="vertical" size={8} style={{ width: '100%' }}>
            <Typography.Text>公司：{parsed.companyName || '未识别'}</Typography.Text>
            <Typography.Text>岗位：{parsed.position || '未识别'}</Typography.Text>
            <Typography.Text>城市：{parsed.city || '未识别'}</Typography.Text>
            <Typography.Text>薪资：{parsed.salary || '未识别'}</Typography.Text>
            <Typography.Text>公司类型：{parsed.companyType || '未识别'}</Typography.Text>
            <Typography.Text>招聘类型：{parsed.jobType || '未识别'}</Typography.Text>
            <Typography.Text>行业：{parsed.industry || '未识别'}</Typography.Text>
            <Typography.Text>技术栈：{parsed.techStack || '未识别'}</Typography.Text>
          </Space>
        </div>
      </Space>
    </Drawer>
  )
}

function parseJobDescription(sourceText: string): Partial<JobApplication> {
  const normalizedText = sourceText.trim()
  const lines = normalizedText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)

  const salaryMatch = normalizedText.match(/(\d+(?:\.\d+)?\s*(?:k|K|万)(?:\s*[xX*]\s*\d+)?)|(\d+(?:\.\d+)?\s*\/\s*天)/)
  const companyLine = lines.find((line) => /公司|企业|集团|科技|网络|信息|有限/.test(line))
  const position = positionRules.find((item) => normalizedText.includes(item))
  const city = cityCandidates.find((item) => normalizedText.includes(item))
  const companyType = companyTypeRules.find((rule) => rule.pattern.test(normalizedText))?.value || '中小公司'
  const jobType = jobTypeRules.find((rule) => rule.pattern.test(normalizedText))?.value || '日常实习'
  const industry = industryRules.find((rule) => rule.pattern.test(normalizedText))?.value
  const techStack = techKeywordLabels.filter((_, index) => techKeywordRules[index].test(normalizedText)).join('、')
  const companyName = companyLine?.replace(/^公司[:：]?/, '') || lines[0] || ''

  return {
    id: nanoid(),
    companyName,
    companyType,
    industry,
    city: city || '',
    position: position || '',
    jobType,
    salary: salaryMatch?.[0]?.replace(/\s+/g, '') || '',
    skillRequirement: normalizedText,
    techStack,
    jdText: normalizedText,
    status: '待投递',
    offerReceived: false,
    canConvert: false,
    interviews: [],
    offerDetails: {
      salary: '',
      benefits: '',
      startDate: '',
    },
    decisionScores: {
      salary: 5,
      development: 5,
      location: 5,
      brand: 5,
      workload: 5,
    },
  }
}
