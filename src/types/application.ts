import type { ApplicationStatus } from '../constants/status'

export const COMPANY_TYPES = ['大厂', '独角兽', '传统企业', '中小公司', '创业公司', '外企'] as const
export const INDUSTRIES = ['互联网', '金融', '制造', '咨询', '教育', '消费', '医疗'] as const
export const COMPANY_SIZES = ['50人以下', '50-150人', '150-500人', '500-2000人', '2000人以上'] as const
export const JOB_TYPES = ['校招全职', '暑期实习', '日常实习'] as const
export const APPLY_CHANNELS = ['官网', '内推', '校招平台', '招聘网站', '猎头'] as const
export const INTERVIEW_FORMATS = ['线上', '线下'] as const
export const INTERVIEW_LANGUAGES = ['中文', '英文'] as const
export const INTERVIEW_TYPES = ['技术面', 'HR面', '群面', '业务面', '其他'] as const
export const INTERVIEW_RESULTS = ['通过', '未通过', '等待中'] as const

export type CompanyType = (typeof COMPANY_TYPES)[number]
export type Industry = (typeof INDUSTRIES)[number]
export type CompanySize = (typeof COMPANY_SIZES)[number]
export type JobType = (typeof JOB_TYPES)[number]
export type ApplyChannel = (typeof APPLY_CHANNELS)[number]
export type InterviewFormat = (typeof INTERVIEW_FORMATS)[number]
export type InterviewLanguage = (typeof INTERVIEW_LANGUAGES)[number]
export type InterviewType = (typeof INTERVIEW_TYPES)[number]
export type InterviewResult = (typeof INTERVIEW_RESULTS)[number]

export interface InterviewItem {
  id: string
  round: string
  date: string
  location?: string
  format: InterviewFormat
  platform?: string
  language: InterviewLanguage
  type: InterviewType
  interviewer?: string
  result?: InterviewResult
  notes?: string
}

export interface InterviewConflictItem {
  interviewId: string
  applicationId: string
  companyName: string
  round: string
  date: string
  kind?: 'interview' | 'course'
  courseName?: string
}

export interface OfferDetails {
  salary?: string
  benefits?: string
  startDate?: string
}

export interface DecisionScores {
  salary: number
  development: number
  location: number
  brand: number
  workload: number
}

export interface CourseItem {
  id: string
  name: string
  weekday: number
  startTime: string
  endTime: string
  location?: string
}

export interface NotificationSettings {
  enabled: boolean
  notifiedKeys: string[]
}

export interface JobApplication {
  id: string
  companyName: string
  companyType: CompanyType
  industry?: Industry
  city: string
  companySize?: CompanySize
  position: string
  department?: string
  majorRequirement?: string
  degreeRequirement?: string
  skillRequirement?: string
  techStack?: string
  jobType: JobType
  headcount?: string
  salary?: string
  workDays?: string
  internDuration?: string
  canConvert?: boolean
  applyChannel?: ApplyChannel
  applyDate?: string
  deadline?: string
  status: ApplicationStatus
  interviews: InterviewItem[]
  hrContact?: string
  referrer?: string
  offerReceived?: boolean
  offerDeadline?: string
  offerDetails?: OfferDetails
  jdLink?: string
  jdText?: string
  notes?: string
  attachments?: string
  decisionScores: DecisionScores
  createdAt: string
  updatedAt: string
}

export interface ApplicationFilters {
  companyType?: CompanyType
  city?: string
  jobType?: JobType
  status?: ApplicationStatus
  industry?: Industry
  interviewLanguage?: InterviewLanguage
  interviewFormat?: InterviewFormat
  interviewType?: InterviewType
  offerReceived?: boolean
  canConvert?: boolean
  salaryMin?: number
  salaryMax?: number
}

export interface TodoItem {
  id: string
  title: string
  description: string
  type: 'interview' | 'deadline' | 'offer' | 'reminder'
  date: string
  companyName: string
}

export interface CalendarEventItem {
  id: string
  title: string
  date: string
  color: string
  applicationId: string
  type: 'interview' | 'deadline' | 'offer'
}
