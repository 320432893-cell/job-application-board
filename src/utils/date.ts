import dayjs from 'dayjs'

export function formatDate(date?: string, fallback = '未设置') {
  if (!date) return fallback
  return dayjs(date).format('YYYY-MM-DD')
}

export function formatDateTime(date?: string, fallback = '未设置') {
  if (!date) return fallback
  return dayjs(date).format('YYYY-MM-DD HH:mm')
}

export function isToday(date?: string) {
  return Boolean(date) && dayjs(date).isSame(dayjs(), 'day')
}

export function isWithinDays(date: string | undefined, days: number) {
  if (!date) return false
  const target = dayjs(date)
  const now = dayjs()
  return target.isAfter(now.subtract(1, 'day')) && target.diff(now, 'day', true) <= days
}

export function parseTimeToMinutes(value: string) {
  const [hour, minute] = value.split(':').map(Number)
  return hour * 60 + minute
}

export function isTimeRangeOverlapping(startA: number, endA: number, startB: number, endB: number) {
  return startA < endB && startB < endA
}
