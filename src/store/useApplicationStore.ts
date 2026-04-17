import dayjs from 'dayjs'
import { create } from 'zustand'
import { DEFAULT_FILTERS } from '../constants/filters'
import { APPLICATION_STATUSES, type ApplicationStatus } from '../constants/status'
import { mockApplications } from '../data/mockApplications'
import { mockCourses } from '../data/mockCourses'
import type {
  ApplicationFilters,
  CalendarEventItem,
  CourseItem,
  InterviewConflictItem,
  JobApplication,
  NotificationSettings,
  TodoItem,
} from '../types/application'
import { isTimeRangeOverlapping, isToday, isWithinDays, parseTimeToMinutes } from '../utils/date'
import { loadApplications, saveApplications } from '../utils/storage'

interface ApplicationStore {
  applications: JobApplication[]
  courses: CourseItem[]
  notificationSettings: NotificationSettings
  searchKeyword: string
  filters: ApplicationFilters
  selectedOfferIds: string[]
  selectedApplicationIds: string[]
  initialize: () => void
  setSearchKeyword: (keyword: string) => void
  setFilters: (filters: ApplicationFilters) => void
  resetFilters: () => void
  loadMockData: () => void
  createApplication: (application: JobApplication) => void
  updateApplication: (application: JobApplication) => void
  deleteApplication: (id: string) => void
  deleteApplications: (ids: string[]) => void
  updateApplicationStatus: (id: string, status: ApplicationStatus) => void
  updateApplicationsStatus: (ids: string[], status: ApplicationStatus) => void
  replaceApplications: (applications: JobApplication[]) => void
  toggleOfferSelection: (id: string) => void
  clearOfferSelection: () => void
  toggleApplicationSelection: (id: string) => void
  setApplicationSelection: (ids: string[]) => void
  clearApplicationSelection: () => void
  setNotificationEnabled: (enabled: boolean) => void
  markNotificationSent: (key: string) => void
}

function persist(applications: JobApplication[]) {
  saveApplications(applications)
  return applications
}

function normalizeApplication(application: JobApplication): JobApplication {
  return {
    ...application,
    industry: application.industry,
    companySize: application.companySize,
    department: application.department || '',
    majorRequirement: application.majorRequirement || '',
    degreeRequirement: application.degreeRequirement || '',
    skillRequirement: application.skillRequirement || '',
    techStack: application.techStack || '',
    headcount: application.headcount || '',
    workDays: application.workDays || '',
    internDuration: application.internDuration || '',
    canConvert: application.canConvert ?? false,
    applyChannel: application.applyChannel,
    hrContact: application.hrContact || '',
    referrer: application.referrer || '',
    offerReceived: application.offerReceived ?? false,
    offerDeadline: application.offerDeadline,
    offerDetails: {
      salary: application.offerDetails?.salary || '',
      benefits: application.offerDetails?.benefits || '',
      startDate: application.offerDetails?.startDate || '',
    },
    jdLink: application.jdLink || '',
    jdText: application.jdText || '',
    notes: application.notes || '',
    attachments: application.attachments || '',
    decisionScores: {
      salary: application.decisionScores?.salary ?? 5,
      development: application.decisionScores?.development ?? 5,
      location: application.decisionScores?.location ?? 5,
      brand: application.decisionScores?.brand ?? 5,
      workload: application.decisionScores?.workload ?? 5,
    },
    interviews: (application.interviews || []).map((interview) => ({
      platform: interview.platform || '',
      interviewer: interview.interviewer || '',
      result: interview.result || '等待中',
      ...interview,
    })),
  }
}

function extractSalaryValue(value?: string) {
  if (!value) return 0
  const normalized = value.toLowerCase().replace(/[,，\s]/g, '')
  const matched = normalized.match(/\d+(\.\d+)?/)
  if (!matched) return 0
  const amount = Number(matched[0])
  if (normalized.includes('k')) return amount * 1000
  if (normalized.includes('万')) return amount * 10000
  return amount
}

export const useApplicationStore = create<ApplicationStore>((set) => ({
  applications: [],
  courses: mockCourses,
  notificationSettings: {
    enabled: false,
    notifiedKeys: [],
  },
  searchKeyword: '',
  filters: DEFAULT_FILTERS,
  selectedOfferIds: [],
  selectedApplicationIds: [],
  initialize: () => {
    const stored = loadApplications()
    const applications = (stored?.length ? stored : mockApplications).map(normalizeApplication)
    persist(applications)
    set({ applications })
  },
  setSearchKeyword: (searchKeyword) => set({ searchKeyword }),
  setFilters: (filters) => set({ filters }),
  resetFilters: () => set({ filters: DEFAULT_FILTERS, searchKeyword: '' }),
  loadMockData: () =>
    set({
      applications: persist(mockApplications),
      courses: mockCourses,
      notificationSettings: {
        enabled: false,
        notifiedKeys: [],
      },
      selectedOfferIds: [],
      selectedApplicationIds: [],
    }),
  createApplication: (application) =>
    set((state) => ({
      applications: persist([normalizeApplication(application), ...state.applications]),
    })),
  updateApplication: (application) =>
    set((state) => ({
      applications: persist(
        state.applications.map((item) => (item.id === application.id ? normalizeApplication(application) : item)),
      ),
    })),
  deleteApplication: (id) =>
    set((state) => ({
      applications: persist(state.applications.filter((item) => item.id !== id)),
      selectedOfferIds: state.selectedOfferIds.filter((item) => item !== id),
      selectedApplicationIds: state.selectedApplicationIds.filter((item) => item !== id),
    })),
  deleteApplications: (ids) =>
    set((state) => ({
      applications: persist(state.applications.filter((item) => !ids.includes(item.id))),
      selectedOfferIds: state.selectedOfferIds.filter((item) => !ids.includes(item)),
      selectedApplicationIds: state.selectedApplicationIds.filter((item) => !ids.includes(item)),
    })),
  updateApplicationStatus: (id, status) =>
    set((state) => ({
      applications: persist(
        state.applications.map((item) =>
          item.id === id
            ? {
                ...item,
                status,
                updatedAt: new Date().toISOString(),
              }
            : item,
        ),
      ),
    })),
  updateApplicationsStatus: (ids, status) =>
    set((state) => ({
      applications: persist(
        state.applications.map((item) =>
          ids.includes(item.id)
            ? {
                ...item,
                status,
                updatedAt: new Date().toISOString(),
              }
            : item,
        ),
      ),
      selectedApplicationIds: state.selectedApplicationIds.filter((item) => !ids.includes(item)),
    })),
  replaceApplications: (applications) =>
    set({
      applications: persist(applications.map(normalizeApplication)),
      selectedOfferIds: [],
      selectedApplicationIds: [],
    }),
  toggleOfferSelection: (id) =>
    set((state) => ({
      selectedOfferIds: state.selectedOfferIds.includes(id)
        ? state.selectedOfferIds.filter((item) => item !== id)
        : [...state.selectedOfferIds, id],
    })),
  clearOfferSelection: () => set({ selectedOfferIds: [] }),
  toggleApplicationSelection: (id) =>
    set((state) => ({
      selectedApplicationIds: state.selectedApplicationIds.includes(id)
        ? state.selectedApplicationIds.filter((item) => item !== id)
        : [...state.selectedApplicationIds, id],
    })),
  setApplicationSelection: (ids) => set({ selectedApplicationIds: ids }),
  clearApplicationSelection: () => set({ selectedApplicationIds: [] }),
  setNotificationEnabled: (enabled) =>
    set((state) => ({
      notificationSettings: {
        ...state.notificationSettings,
        enabled,
      },
    })),
  markNotificationSent: (key) =>
    set((state) => ({
      notificationSettings: {
        ...state.notificationSettings,
        notifiedKeys: state.notificationSettings.notifiedKeys.includes(key)
          ? state.notificationSettings.notifiedKeys
          : [...state.notificationSettings.notifiedKeys, key],
      },
    })),
}))

export function useFilteredApplications() {
  const applications = useApplicationStore((state) => state.applications)
  const searchKeyword = useApplicationStore((state) => state.searchKeyword)
  const filters = useApplicationStore((state) => state.filters)

  return applications.filter((application) => {
    const keyword = searchKeyword.trim().toLowerCase()
    const matchesKeyword =
      !keyword ||
      [application.companyName, application.position, application.city, application.industry, application.department]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(keyword)

    const salaryValue = extractSalaryValue(application.offerDetails?.salary || application.salary)
    const matchesInterviewLanguage =
      !filters.interviewLanguage || application.interviews.some((item) => item.language === filters.interviewLanguage)
    const matchesInterviewFormat =
      !filters.interviewFormat || application.interviews.some((item) => item.format === filters.interviewFormat)
    const matchesInterviewType =
      !filters.interviewType || application.interviews.some((item) => item.type === filters.interviewType)

    const matchesFilters =
      (!filters.companyType || application.companyType === filters.companyType) &&
      (!filters.city || application.city === filters.city) &&
      (!filters.jobType || application.jobType === filters.jobType) &&
      (!filters.status || application.status === filters.status) &&
      (!filters.industry || application.industry === filters.industry) &&
      (filters.offerReceived === undefined || application.offerReceived === filters.offerReceived) &&
      (filters.canConvert === undefined || application.canConvert === filters.canConvert) &&
      matchesInterviewLanguage &&
      matchesInterviewFormat &&
      matchesInterviewType &&
      (filters.salaryMin === undefined || salaryValue >= filters.salaryMin) &&
      (filters.salaryMax === undefined || salaryValue <= filters.salaryMax)

    return matchesKeyword && matchesFilters
  })
}

export function useApplicationsByStatus() {
  const filteredApplications = useFilteredApplications()

  return APPLICATION_STATUSES.map((status) => ({
    status,
    items: filteredApplications.filter((application) => application.status === status),
  }))
}

export function useTodoItems(): TodoItem[] {
  const applications = useApplicationStore((state) => state.applications)

  return applications
    .flatMap((application) => {
      const todos: TodoItem[] = []

      if (isWithinDays(application.deadline, 3) && application.status === '待投递') {
        todos.push({
          id: `${application.id}-deadline`,
          title: '尽快投递申请',
          description: `${application.position} 截止日期临近`,
          type: 'deadline',
          date: application.deadline!,
          companyName: application.companyName,
        })
      }

      if (application.offerReceived && isWithinDays(application.offerDeadline, 2)) {
        todos.push({
          id: `${application.id}-offer`,
          title: '尽快答复 Offer',
          description: `${application.position} 需要确认去向`,
          type: 'offer',
          date: application.offerDeadline!,
          companyName: application.companyName,
        })
      }

      application.interviews.forEach((interview) => {
        if (isToday(interview.date)) {
          todos.push({
            id: interview.id,
            title: '今天有面试',
            description: `${interview.round} · ${interview.type}`,
            type: 'interview',
            date: interview.date,
            companyName: application.companyName,
          })
        }

        if (isWithinDays(interview.date, 1) && !isToday(interview.date)) {
          const reminders: string[] = []
          if (interview.language === '英文') reminders.push('准备英文自我介绍')
          if (interview.format === '线下') reminders.push('提前查路线和出发时间')
          if (interview.type === '技术面') reminders.push(`复习 ${application.techStack || '技术栈'}`)
          if (reminders.length > 0) {
            todos.push({
              id: `${interview.id}-reminder`,
              title: '面试准备提醒',
              description: reminders.join('；'),
              type: 'reminder',
              date: interview.date,
              companyName: application.companyName,
            })
          }
        }
      })

      return todos
    })
    .sort((a, b) => dayjs(a.date).valueOf() - dayjs(b.date).valueOf())
}

export function useCalendarEvents(): CalendarEventItem[] {
  const applications = useApplicationStore((state) => state.applications)

  return applications.flatMap((application) => {
    const events: CalendarEventItem[] = []

    if (application.deadline) {
      events.push({
        id: `${application.id}-deadline`,
        title: `${application.companyName} 截止`,
        date: application.deadline,
        color: '#ef4444',
        applicationId: application.id,
        type: 'deadline',
      })
    }

    if (application.offerReceived && application.offerDeadline) {
      events.push({
        id: `${application.id}-offer`,
        title: `${application.companyName} Offer 答复`,
        date: application.offerDeadline,
        color: '#22c55e',
        applicationId: application.id,
        type: 'offer',
      })
    }

    application.interviews.forEach((interview) => {
      events.push({
        id: interview.id,
        title: `${application.companyName} ${interview.round}`,
        date: interview.date,
        color: interview.language === '英文' ? '#8b5cf6' : '#3b82f6',
        applicationId: application.id,
        type: 'interview',
      })
    })

    return events
  })
}

export function useOfferApplications() {
  const applications = useApplicationStore((state) => state.applications)
  return applications.filter((application) => application.status === 'Offer' || application.offerReceived)
}

export function useApplicationConflicts(): InterviewConflictItem[] {
  const applications = useApplicationStore((state) => state.applications)
  const courses = useApplicationStore((state) => state.courses)

  const interviews = applications.flatMap((application) =>
    application.interviews.map((interview) => ({
      interviewId: interview.id,
      applicationId: application.id,
      companyName: application.companyName,
      round: interview.round,
      date: interview.date,
    })),
  )

  const interviewConflicts = interviews.filter((interview, index) => {
    const start = dayjs(interview.date)
    const end = start.add(1, 'hour')

    return interviews.some((candidate, candidateIndex) => {
      if (candidateIndex === index) return false
      const candidateStart = dayjs(candidate.date)
      const candidateEnd = candidateStart.add(1, 'hour')
      return start.isBefore(candidateEnd) && candidateStart.isBefore(end)
    })
  })

  const courseConflicts = interviews.flatMap((interview) => {
    const interviewDate = dayjs(interview.date)
    const interviewWeekday = interviewDate.day()
    const interviewStart = interviewDate.hour() * 60 + interviewDate.minute()
    const interviewEnd = interviewStart + 60

    return courses
      .filter((course) => {
        if (course.weekday !== interviewWeekday) return false
        const courseStart = parseTimeToMinutes(course.startTime)
        const courseEnd = parseTimeToMinutes(course.endTime)
        return isTimeRangeOverlapping(interviewStart, interviewEnd, courseStart, courseEnd)
      })
      .map((course) => ({
        ...interview,
        kind: 'course' as const,
        courseName: course.name,
      }))
  })

  return [...interviewConflicts, ...courseConflicts]
}

export function useConflictApplicationIds() {
  const conflicts = useApplicationConflicts()
  return Array.from(new Set(conflicts.map((item) => item.applicationId)))
}

export function useNotificationPromptItems() {
  const items = useTodoItems()
  const notificationSettings = useApplicationStore((state) => state.notificationSettings)

  if (!notificationSettings.enabled) return []

  return items.filter((item) => !notificationSettings.notifiedKeys.includes(item.id))
}
