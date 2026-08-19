import { useEffect, useState } from 'react'

export function daysUntil(dateStr: string): number {
  const t = new Date(dateStr).getTime()
  if (Number.isNaN(t)) return NaN
  return Math.ceil((t - Date.now()) / 86400000)
}

type Tone = 'soon' | 'bad' | 'dim' | 'ok'
export function toneFor(days: number): Tone {
  if (Number.isNaN(days)) return 'dim'
  if (days < 0) return 'bad'
  if (days <= 21) return 'soon'
  return 'ok'
}

export function countdownLabel(days: number): string {
  if (Number.isNaN(days)) return '-'
  if (days < 0) return `过期 ${Math.abs(days)}d`
  if (days === 0) return '今日截止'
  if (days === 1) return '明日截止'
  if (days <= 30) return `${days}d`
  const m = Math.floor(days / 30)
  return `${m}mo`
}

export default function CountdownPill({ date, round, applicantGroup }: { date: string; round?: string; applicantGroup?: string }) {
  const [, force] = useState(0)
  useEffect(() => {
    const id = setInterval(() => force((n) => n + 1), 60000)
    return () => clearInterval(id)
  }, [])
  const d = daysUntil(date)
  const tone = toneFor(d)
  return (
    <span className="dl-row">
      {round && <span className="rnd">{applicantGroup && applicantGroup !== 'Unknown' ? `${applicantGroup} · ` : ''}{round}</span>}
      <span className="dt">{date}</span>
      <span className={`cd ${tone}`}>{countdownLabel(d)}</span>
    </span>
  )
}
