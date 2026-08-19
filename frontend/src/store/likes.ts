import { useSyncExternalStore } from 'react'
import type { AppStatus, UserData } from '../types'

const KEY = 'rankingselect:user'

const defaultData: UserData = {
  likes: [],
  checklist: {},
  status: {},
  settings: { language: 'zh', sortBy: 'deadline' },
}

let data: UserData = read()
const listeners = new Set<() => void>()

function read(): UserData {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? { ...defaultData, ...JSON.parse(raw) } : defaultData
    if (!parsed.status) parsed.status = {}
    if (!parsed.checklist) parsed.checklist = {}
    if (!parsed.likes) parsed.likes = []
    return parsed
  } catch {
    return defaultData
  }
}

function persist() {
  try { localStorage.setItem(KEY, JSON.stringify(data)) } catch {}
  listeners.forEach((l) => l())
}

export function getUser(): UserData { return data }

export function subscribe(cb: () => void) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function useUser(): UserData {
  return useSyncExternalStore(subscribe, getUser, getUser)
}

export function isLiked(universityId: string): boolean {
  return data.likes.includes(universityId)
}

export function toggleLike(universityId: string): void {
  const wasLiked = data.likes.includes(universityId)
  data = {
    ...data,
    likes: wasLiked
      ? data.likes.filter((id) => id !== universityId)
      : [...data.likes, universityId],
    status: wasLiked
      ? (() => { const s = { ...data.status }; delete s[universityId]; return s })()
      : { ...data.status, [universityId]: data.status[universityId] || 'pending' },
  }
  persist()
}

export function statusOf(universityId: string): AppStatus {
  return data.status[universityId] || 'pending'
}

export function setStatus(universityId: string, status: AppStatus): void {
  data = { ...data, status: { ...data.status, [universityId]: status } }
  persist()
}

export function toggleMaterial(programId: string, material: string): void {
  const cur = data.checklist[programId] || []
  const next = cur.includes(material)
    ? cur.filter((m) => m !== material)
    : [...cur, material]
  data = { ...data, checklist: { ...data.checklist, [programId]: next } }
  persist()
}

export function setSortBy(sortBy: UserData['settings']['sortBy']): void {
  data = { ...data, settings: { ...data.settings, sortBy } }
  persist()
}