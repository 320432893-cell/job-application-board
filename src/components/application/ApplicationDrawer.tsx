import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { nanoid } from 'nanoid'
import {
  Button,
  Checkbox,
  DatePicker,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  Typography,
} from 'antd'
import dayjs from 'dayjs'
import { APPLICATION_STATUSES } from '../../constants/status'
import {
  APPLY_CHANNELS,
  COMPANY_SIZES,
  COMPANY_TYPES,
  INDUSTRIES,
  INTERVIEW_FORMATS,
  INTERVIEW_LANGUAGES,
  INTERVIEW_RESULTS,
  INTERVIEW_TYPES,
  JOB_TYPES,
  type JobApplication,
} from '../../types/application'

interface ApplicationDrawerProps {
  open: boolean
  mode: 'create' | 'view' | 'edit'
  application?: JobApplication
  initialValues?: Partial<JobApplication>
  onClose: () => void
  onSubmit: (application: JobApplication) => void
}

export function ApplicationDrawer({ open, mode, application, initialValues, onClose, onSubmit }: ApplicationDrawerProps) {
  const [form] = Form.useForm()
  const isView = mode === 'view'

  return (
    <Drawer
      open={open}
      width={720}
      title={mode === 'create' ? '新建申请' : mode === 'edit' ? '编辑申请' : '申请详情'}
      onClose={onClose}
      destroyOnClose
      afterOpenChange={(visible) => {
        if (!visible) return
        form.setFieldsValue(
          application
            ? {
                ...application,
                applyDate: application.applyDate ? dayjs(application.applyDate) : undefined,
                deadline: application.deadline ? dayjs(application.deadline) : undefined,
                offerDeadline: application.offerDeadline ? dayjs(application.offerDeadline) : undefined,
                offerDetails: {
                  ...application.offerDetails,
                  startDate: application.offerDetails?.startDate ? dayjs(application.offerDetails.startDate) : undefined,
                },
                interviews: application.interviews.map((interview) => ({
                  ...interview,
                  date: interview.date ? dayjs(interview.date) : undefined,
                })),
              }
            : {
                companyName: initialValues?.companyName,
                companyType: initialValues?.companyType || '大厂',
                industry: initialValues?.industry,
                city: initialValues?.city,
                companySize: initialValues?.companySize,
                position: initialValues?.position,
                department: initialValues?.department,
                majorRequirement: initialValues?.majorRequirement,
                degreeRequirement: initialValues?.degreeRequirement,
                skillRequirement: initialValues?.skillRequirement,
                techStack: initialValues?.techStack,
                jobType: initialValues?.jobType || '校招全职',
                headcount: initialValues?.headcount,
                salary: initialValues?.salary,
                workDays: initialValues?.workDays,
                internDuration: initialValues?.internDuration,
                canConvert: initialValues?.canConvert || false,
                applyChannel: initialValues?.applyChannel,
                applyDate: initialValues?.applyDate ? dayjs(initialValues.applyDate) : undefined,
                deadline: initialValues?.deadline ? dayjs(initialValues.deadline) : undefined,
                status: initialValues?.status || '待投递',
                offerReceived: initialValues?.offerReceived || false,
                offerDeadline: initialValues?.offerDeadline ? dayjs(initialValues.offerDeadline) : undefined,
                hrContact: initialValues?.hrContact,
                referrer: initialValues?.referrer,
                jdLink: initialValues?.jdLink,
                jdText: initialValues?.jdText,
                notes: initialValues?.notes,
                attachments: initialValues?.attachments,
                decisionScores: {
                  salary: initialValues?.decisionScores?.salary ?? 5,
                  development: initialValues?.decisionScores?.development ?? 5,
                  location: initialValues?.decisionScores?.location ?? 5,
                  brand: initialValues?.decisionScores?.brand ?? 5,
                  workload: initialValues?.decisionScores?.workload ?? 5,
                },
                interviews: (initialValues?.interviews || []).map((interview) => ({
                  ...interview,
                  date: interview.date ? dayjs(interview.date) : undefined,
                })),
                offerDetails: {
                  salary: initialValues?.offerDetails?.salary,
                  benefits: initialValues?.offerDetails?.benefits,
                  startDate: initialValues?.offerDetails?.startDate ? dayjs(initialValues.offerDetails.startDate) : undefined,
                },
              },
        )
      }}
      extra={
        !isView && (
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" onClick={() => form.submit()}>
              保存
            </Button>
          </Space>
        )
      }
    >
      <Form
        form={form}
        layout="vertical"
        disabled={isView}
        onFinish={(values) => {
          const now = new Date().toISOString()
          onSubmit({
            id: application?.id || nanoid(),
            companyName: values.companyName,
            companyType: values.companyType,
            industry: values.industry,
            city: values.city,
            companySize: values.companySize,
            position: values.position,
            department: values.department,
            majorRequirement: values.majorRequirement,
            degreeRequirement: values.degreeRequirement,
            skillRequirement: values.skillRequirement,
            techStack: values.techStack,
            jobType: values.jobType,
            headcount: values.headcount,
            salary: values.salary,
            workDays: values.workDays,
            internDuration: values.internDuration,
            canConvert: values.canConvert,
            applyChannel: values.applyChannel,
            applyDate: values.applyDate?.toISOString(),
            deadline: values.deadline?.toISOString(),
            status: values.status,
            interviews: (values.interviews || []).map((interview: JobApplication['interviews'][number]) => ({
              id: interview.id || nanoid(),
              round: interview.round,
              date: dayjs.isDayjs(interview.date) ? interview.date.toISOString() : interview.date,
              location: interview.location,
              format: interview.format,
              platform: interview.platform,
              language: interview.language,
              type: interview.type,
              interviewer: interview.interviewer,
              result: interview.result,
              notes: interview.notes,
            })),
            hrContact: values.hrContact,
            referrer: values.referrer,
            offerReceived: values.offerReceived,
            offerDeadline: values.offerDeadline?.toISOString(),
            offerDetails: {
              salary: values.offerDetails?.salary,
              benefits: values.offerDetails?.benefits,
              startDate: values.offerDetails?.startDate?.toISOString?.() || values.offerDetails?.startDate,
            },
            jdLink: values.jdLink,
            jdText: values.jdText,
            notes: values.notes,
            attachments: values.attachments,
            decisionScores: {
              salary: values.decisionScores?.salary ?? 5,
              development: values.decisionScores?.development ?? 5,
              location: values.decisionScores?.location ?? 5,
              brand: values.decisionScores?.brand ?? 5,
              workload: values.decisionScores?.workload ?? 5,
            },
            createdAt: application?.createdAt || now,
            updatedAt: now,
          })
          onClose()
        }}
      >
        <Divider>公司信息</Divider>
        <Form.Item name="companyName" label="公司名称" rules={[{ required: true, message: '请输入公司名称' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="companyType" label="公司类型" rules={[{ required: true, message: '请选择公司类型' }]}>
          <Select options={COMPANY_TYPES.map((item) => ({ label: item, value: item }))} />
        </Form.Item>
        <Form.Item name="industry" label="行业">
          <Select allowClear options={INDUSTRIES.map((item) => ({ label: item, value: item }))} />
        </Form.Item>
        <Form.Item name="city" label="工作城市" rules={[{ required: true, message: '请输入工作城市' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="companySize" label="公司规模">
          <Select allowClear options={COMPANY_SIZES.map((item) => ({ label: item, value: item }))} />
        </Form.Item>

        <Divider>岗位信息</Divider>
        <Form.Item name="position" label="岗位名称" rules={[{ required: true, message: '请输入岗位名称' }]}>
          <Input />
        </Form.Item>
        <Form.Item name="department" label="部门 / 业务线">
          <Input />
        </Form.Item>
        <Form.Item name="majorRequirement" label="专业要求">
          <Input />
        </Form.Item>
        <Form.Item name="degreeRequirement" label="学历要求">
          <Input />
        </Form.Item>
        <Form.Item name="skillRequirement" label="技能要求">
          <Input.TextArea rows={3} />
        </Form.Item>
        <Form.Item name="techStack" label="技术栈">
          <Input />
        </Form.Item>

        <Divider>招聘信息</Divider>
        <Form.Item name="jobType" label="招聘类型" rules={[{ required: true, message: '请选择招聘类型' }]}>
          <Select options={JOB_TYPES.map((item) => ({ label: item, value: item }))} />
        </Form.Item>
        <Form.Item name="headcount" label="招聘人数">
          <Input />
        </Form.Item>
        <Form.Item name="salary" label="薪资 / 补贴">
          <Input />
        </Form.Item>
        <Form.Item name="workDays" label="每周出勤天数">
          <Input />
        </Form.Item>
        <Form.Item name="internDuration" label="实习时长要求">
          <Input />
        </Form.Item>
        <Form.Item name="canConvert" label="是否可转正" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Divider>流程信息</Divider>
        <Form.Item name="applyChannel" label="申请渠道">
          <Select allowClear options={APPLY_CHANNELS.map((item) => ({ label: item, value: item }))} />
        </Form.Item>
        <Form.Item name="applyDate" label="投递时间">
          <DatePicker showTime style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="deadline" label="截止日期">
          <DatePicker showTime style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="status" label="当前状态" rules={[{ required: true, message: '请选择当前状态' }]}>
          <Select options={APPLICATION_STATUSES.map((item) => ({ label: item, value: item }))} />
        </Form.Item>

        <Divider>面试信息</Divider>
        <Form.List name="interviews">
          {(fields, { add, remove }) => (
            <Space direction="vertical" size={16} style={{ width: '100%' }}>
              {fields.map((field, index) => (
                <div key={field.key} style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: 16 }}>
                  <Space align="center" style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                    <Typography.Text strong>第 {index + 1} 轮面试</Typography.Text>
                    {!isView ? (
                      <Button danger type="text" icon={<DeleteOutlined />} onClick={() => remove(field.name)}>
                        删除
                      </Button>
                    ) : null}
                  </Space>
                  <Form.Item name={[field.name, 'id']} hidden>
                    <Input />
                  </Form.Item>
                  <Form.Item name={[field.name, 'round']} label="轮次" rules={[{ required: true, message: '请输入面试轮次' }]}>
                    <Input />
                  </Form.Item>
                  <Form.Item name={[field.name, 'date']} label="面试时间" rules={[{ required: true, message: '请选择面试时间' }]}>
                    <DatePicker showTime style={{ width: '100%' }} />
                  </Form.Item>
                  <Form.Item name={[field.name, 'location']} label="地点">
                    <Input />
                  </Form.Item>
                  <Form.Item name={[field.name, 'format']} label="形式" rules={[{ required: true, message: '请选择面试形式' }]}>
                    <Select options={INTERVIEW_FORMATS.map((item) => ({ label: item, value: item }))} />
                  </Form.Item>
                  <Form.Item name={[field.name, 'platform']} label="平台">
                    <Input placeholder="腾讯会议 / Zoom / 电话" />
                  </Form.Item>
                  <Form.Item name={[field.name, 'language']} label="语言" rules={[{ required: true, message: '请选择面试语言' }]}>
                    <Select options={INTERVIEW_LANGUAGES.map((item) => ({ label: item, value: item }))} />
                  </Form.Item>
                  <Form.Item name={[field.name, 'type']} label="类型" rules={[{ required: true, message: '请选择面试类型' }]}>
                    <Select options={INTERVIEW_TYPES.map((item) => ({ label: item, value: item }))} />
                  </Form.Item>
                  <Form.Item name={[field.name, 'interviewer']} label="面试官信息">
                    <Input />
                  </Form.Item>
                  <Form.Item name={[field.name, 'result']} label="面试结果">
                    <Select allowClear options={INTERVIEW_RESULTS.map((item) => ({ label: item, value: item }))} />
                  </Form.Item>
                  <Form.Item name={[field.name, 'notes']} label="面试记录">
                    <Input.TextArea rows={3} />
                  </Form.Item>
                </div>
              ))}
              {!isView ? (
                <Button
                  type="dashed"
                  icon={<PlusOutlined />}
                  onClick={() =>
                    add({
                      id: nanoid(),
                      format: '线上',
                      language: '中文',
                      type: '技术面',
                      result: '等待中',
                    })
                  }
                >
                  新增一轮面试
                </Button>
              ) : null}
            </Space>
          )}
        </Form.List>

        <Divider>联系人</Divider>
        <Form.Item name="hrContact" label="HR 联系方式">
          <Input />
        </Form.Item>
        <Form.Item name="referrer" label="内推人">
          <Input />
        </Form.Item>

        <Divider>Offer 相关</Divider>
        <Form.Item name="offerReceived" valuePropName="checked">
          <Checkbox>已收到 Offer</Checkbox>
        </Form.Item>
        <Form.Item name="offerDeadline" label="Offer 答复截止时间">
          <DatePicker showTime style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name={['offerDetails', 'salary']} label="Offer 薪资">
          <Input />
        </Form.Item>
        <Form.Item name={['offerDetails', 'benefits']} label="Offer 福利">
          <Input.TextArea rows={2} />
        </Form.Item>
        <Form.Item name={['offerDetails', 'startDate']} label="入职时间">
          <DatePicker style={{ width: '100%' }} />
        </Form.Item>

        <Divider>其他信息</Divider>
        <Form.Item name="jdLink" label="JD 链接">
          <Input />
        </Form.Item>
        <Form.Item name="jdText" label="JD 原文">
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item name="notes" label="备注">
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item name="attachments" label="附件">
          <Input placeholder="简历 / 证书等文件名" />
        </Form.Item>

        <Divider>决策评分</Divider>
        <Form.Item name={['decisionScores', 'salary']} label="薪资评分">
          <InputNumber min={0} max={10} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name={['decisionScores', 'development']} label="发展前景评分">
          <InputNumber min={0} max={10} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name={['decisionScores', 'location']} label="地点评分">
          <InputNumber min={0} max={10} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name={['decisionScores', 'brand']} label="公司品牌评分">
          <InputNumber min={0} max={10} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name={['decisionScores', 'workload']} label="工作强度评分">
          <InputNumber min={0} max={10} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Drawer>
  )
}
