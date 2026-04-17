import type { JobApplication } from '../types/application'

const STORAGE_KEY = 'job-application-board-data'

export function loadApplications() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as JobApplication[]
  } catch {
    return null
  }
}

export function saveApplications(applications: JobApplication[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(applications))
}

export function clearApplications() {
  localStorage.removeItem(STORAGE_KEY)
}
