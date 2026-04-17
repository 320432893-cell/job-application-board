import type { CourseItem } from '../types/application'

export const mockCourses: CourseItem[] = [
  {
    id: 'course-1',
    name: '数据分析课',
    weekday: 2,
    startTime: '14:00',
    endTime: '16:00',
    location: '教学楼 A201',
  },
  {
    id: 'course-2',
    name: '产品设计课',
    weekday: 4,
    startTime: '10:00',
    endTime: '12:00',
    location: '教学楼 B305',
  },
]
