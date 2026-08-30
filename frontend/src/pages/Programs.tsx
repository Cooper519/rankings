import { useMemo, useState } from 'react'
import { Search, ShieldCheck, CalendarClock, FileCheck2 } from 'lucide-react'
import { useData } from '../hooks/useData'
import type { Program } from '../types'
import Reveal from '../components/Reveal'
import CountdownPill from '../components/Countdown'
import LikeButton from '../components/LikeButton'
import { useDrawer } from '../store/drawer'

const foldSearch = (value: string) => value
  .normalize('NFKD')
  .replace(/[\u0300-\u036f]/g, '')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, ' ')
  .trim()

function hasRequirement(p: Program): boolean {
  const r = p.requirements
  return Boolean(r.gpa || r.ielts || r.toefl || r.gre || r.gmat || r.language || r.academic)
}

function subjectLabel(value?: string): string {
  return value && value !== 'General' ? value : '综合/未分类'
}

function requirementText(p: Program): string {
  const r = p.requirements
  const parts = []
  if (r.ielts) parts.push(`IELTS ${r.ielts}`)
  if (r.toefl) parts.push(`TOEFL ${r.toefl}`)
  if (r.gre) parts.push(r.gre)
  if (r.gmat) parts.push(r.gmat)
  if (r.gpa) parts.push(`GPA ${r.gpa}`)
  if (r.language) parts.push(r.language)
  if (r.academic) parts.push(r.academic)
  return parts.join(' · ')
}

export default function Programs() {
  const { uniquePrograms: programs, unis, canonicalById, ready } = useData()
  const { open } = useDrawer()
  const [q, setQ] = useState('')
  const [subject, setSubject] = useState('')
  const [onlyDeadline, setOnlyDeadline] = useState(false)
  const [onlyRequirement, setOnlyRequirement] = useState(false)
  const [onlyVerified, setOnlyVerified] = useState(false)
  const [limit, setLimit] = useState(80)

  const subjects = useMemo(() => Array.from(new Set(programs.map((p) => subjectLabel(p.subject)))).sort(), [programs])

  const filtered = useMemo(() => {
    const needle = foldSearch(q.trim())
    return programs.filter((p) => {
      const uni = unis[canonicalById[p.universityId]] || unis[p.universityId]
      const uniName = uni?.name?.en || p.universityId.replace(/^u_/, '').replace(/_/g, ' ')
      const normalizedSubject = subjectLabel(p.subject)
      if (subject && normalizedSubject !== subject) return false
      if (onlyDeadline && p.deadlines.length === 0) return false
      if (onlyRequirement && !hasRequirement(p)) return false
      if (onlyVerified && !p.verified) return false
      if (needle) {
        const haystack = foldSearch(`${p.program} ${normalizedSubject} ${uniName} ${uni?.country || ''} ${requirementText(p)}`)
        if (!haystack.includes(needle)) return false
      }
      return true
    }).sort((a, b) => {
      if (a.verified !== b.verified) return a.verified ? -1 : 1
      if (hasRequirement(a) !== hasRequirement(b)) return hasRequirement(a) ? -1 : 1
      if (a.deadlines.length !== b.deadlines.length) return b.deadlines.length - a.deadlines.length
      const ua = (unis[a.universityId] || unis[canonicalById[a.universityId]])?.name?.en || ''
      const ub = (unis[b.universityId] || unis[canonicalById[b.universityId]])?.name?.en || ''
      return ua.localeCompare(ub) || a.program.localeCompare(b.program)
    })
  }, [programs, unis, canonicalById, q, subject, onlyDeadline, onlyRequirement, onlyVerified])

  const visible = filtered.slice(0, limit)
  const deadlineCount = programs.filter((p) => p.deadlines.length > 0).length
  const requirementCount = programs.filter(hasRequirement).length
  const verifiedCount = programs.filter((p) => p.verified).length

  return (
    <div className="wrap" style={{ paddingTop: 'calc(var(--nav-h) + 50px)' }}>
      <Reveal>
        <div className="sec-head" style={{ marginBottom: 30 }}>
          <div className="l">
            <span className="no">03 / 项目库</span>
            <h2>硕士项目<em>与申请要求</em></h2>
          </div>
          <p className="note">
            {ready ? `${filtered.length} / ${programs.length}` : '-'} 条项目 · 按学校、专业、材料、语言要求和截止日期筛选。
          </p>
        </div>
      </Reveal>

      <Reveal delay={0.04}>
        <div className="program-stats">
          <div><span>项目总数</span><b className="num">{programs.length}</b></div>
          <div><span>含截止日期</span><b className="num">{deadlineCount}</b></div>
          <div><span>含硬性要求</span><b className="num">{requirementCount}</b></div>
          <div><span>已人工校对</span><b className="num">{verifiedCount}</b></div>
        </div>
      </Reveal>

      <Reveal delay={0.08}>
        <div className="toolbar">
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <Search size={14} style={{ position: 'absolute', left: 12, color: 'var(--ink-4)', pointerEvents: 'none' }} />
            <input
              className="field"
              placeholder="搜索项目 / 学校 / IELTS / TOEFL"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ paddingLeft: 34, minWidth: 280 }}
            />
          </div>
          <select className="field" value={subject} onChange={(e) => setSubject(e.target.value)}>
            <option value="">全部学科</option>
            {subjects.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className={`mbtn${onlyDeadline ? ' solid' : ''}`} data-cursor style={{ padding: '9px 16px', fontSize: 12 }} onClick={() => setOnlyDeadline((v) => !v)}>
            <CalendarClock size={13} /> 有截止
          </button>
          <button className={`mbtn${onlyRequirement ? ' solid' : ''}`} data-cursor style={{ padding: '9px 16px', fontSize: 12 }} onClick={() => setOnlyRequirement((v) => !v)}>
            <FileCheck2 size={13} /> 有要求
          </button>
          <button className={`mbtn${onlyVerified ? ' solid' : ''}`} data-cursor style={{ padding: '9px 16px', fontSize: 12 }} onClick={() => setOnlyVerified((v) => !v)}>
            <ShieldCheck size={13} /> 已校对
          </button>
        </div>
      </Reveal>

      {!ready ? (
        <p className="empty">加载中...</p>
      ) : (
        <div className="program-list">
          {visible.map((p) => {
            const uni = unis[canonicalById[p.universityId]] || unis[p.universityId]
            const req = requirementText(p)
            return (
              <Reveal key={p.id} className="program-row" y={14}>
                <div className="program-row-main" data-cursor onClick={() => open(p.universityId)}>
                  <div className="program-row-title">
                    <span>{p.program}</span>
                    <span className={`badge ${p.verified ? 'ok' : 'wait'}`}>{p.verified ? '已校对' : '待校对'}</span>
                  </div>
                  <div className="program-row-meta">
                    <button className="program-uni" data-cursor onClick={(e) => { e.stopPropagation(); open(p.universityId) }}>
                      {uni?.name?.en || p.universityId}
                    </button>
                    <span>{uni?.country || '-'}</span>
                    <span>{subjectLabel(p.subject)}</span>
                  </div>
                  <div className={`program-row-req${req ? '' : ' muted-req'}`}>
                    {req || '暂无已抽取硬性要求，请以官方源为准'}
                  </div>
                  {p.materials.length > 0 && (
                    <div className="mats compact">
                      {p.materials.slice(0, 7).map((m) => <span key={m} className="mat">{m}</span>)}
                      {p.materials.length > 7 && <span className="mat">+{p.materials.length - 7}</span>}
                    </div>
                  )}
                </div>
                <div className="program-row-side">
                  <LikeButton universityId={p.universityId} size={30} />
                  {p.deadlines.length > 0 ? (
                    <div className="program-deadlines">
                      {p.deadlines.slice(0, 2).map((d, i) => <CountdownPill key={i} date={d.date} round={d.round} applicantGroup={d.applicantGroup} />)}
                    </div>
                  ) : (
                    <span className="muted">暂无截止日期</span>
                  )}
                </div>
              </Reveal>
            )
          })}
        </div>
      )}

      {ready && filtered.length > visible.length && (
        <div style={{ textAlign: 'center', marginTop: 30 }}>
          <button className="mbtn" data-cursor onClick={() => setLimit((l) => l + 80)}>再展开 80 条</button>
        </div>
      )}
    </div>
  )
}
