import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bookmark, CalendarClock, CheckSquare, Heart, ArrowRight, Inbox, ChevronRight, GripVertical } from 'lucide-react'
import { useData } from '../hooks/useData'
import { setStatus, statusOf, useUser } from '../store/likes'
import type { AppStatus, Program } from '../types'
import { useDrawer } from '../store/drawer'
import { daysUntil, toneFor, countdownLabel } from '../components/Countdown'
import Reveal from '../components/Reveal'

const COLS: { key: AppStatus; name: string; dot: string }[] = [
  { key: 'pending', name: '待处理院校', dot: 'var(--ink-5)' },
  { key: 'submitted', name: '已投递', dot: 'var(--accent-2)' },
  { key: 'result', name: '出结果', dot: 'var(--warn)' },
  { key: 'offer', name: '收到 offer', dot: 'var(--ok)' },
]
const STATUS_OPT: { v: AppStatus; label: string }[] = [
  { v: 'pending', label: '待处理' },
  { v: 'submitted', label: '已投递' },
  { v: 'result', label: '出结果' },
  { v: 'offer', label: '收到 offer' },
]
const ORDER: AppStatus[] = ['pending', 'submitted', 'result', 'offer']

interface CardItem {
  uniId: string
  uniName: string
  uniCountry: string
  status: AppStatus
  programs: Program[]
  days: number
  date: string | null
  matsChecked: number
  matsTotal: number
  reqCount: number
}

function hasRequirement(p: Program): boolean {
  const r = p.requirements
  return Boolean(r.gpa || r.ielts || r.toefl || r.gre || r.gmat || r.language || r.academic)
}

export default function Me() {
  const { unis, programsByUni, ready } = useData()
  const user = useUser()
  const { open } = useDrawer()
  const [dragId, setDragId] = useState<string | null>(null)
  const [overCol, setOverCol] = useState<AppStatus | null>(null)

  const items = useMemo<CardItem[]>(() => {
    const out: CardItem[] = []
    for (const uniId of user.likes) {
      const u = unis[uniId]
      if (!u) continue
      const progs = programsByUni[uniId] || []
      const future = progs
        .flatMap((p) => p.deadlines.map((d) => ({ d, days: daysUntil(d.date) })))
        .filter((x) => !Number.isNaN(x.days) && x.days >= 0)
        .sort((a, b) => a.days - b.days)
      const near = future[0]
      let matsTotal = 0, matsChecked = 0
      for (const p of progs) {
        matsTotal += p.materials.length
        matsChecked += (user.checklist[p.id] || []).length
      }
      out.push({
        uniId, uniName: u.name.en, uniCountry: u.country,
        status: statusOf(uniId),
        programs: progs,
        days: near ? near.days : NaN,
        date: near ? near.d.date : null,
        matsChecked, matsTotal,
        reqCount: progs.filter(hasRequirement).length,
      })
    }
    return out
  }, [user.likes, unis, programsByUni, user.checklist, user.status])

  const buckets = useMemo(() => {
    const m: Record<AppStatus, CardItem[]> = { pending: [], submitted: [], result: [], offer: [] }
    for (const it of items) m[it.status].push(it)
    for (const k of ORDER) {
      m[k].sort((a, b) => {
        if (Number.isNaN(a.days) && Number.isNaN(b.days)) return a.uniName.localeCompare(b.uniName)
        if (Number.isNaN(a.days)) return 1
        if (Number.isNaN(b.days)) return -1
        return a.days - b.days
      })
    }
    return m
  }, [items])

  const likedCount = user.likes.length
  const withDeadline = items.filter((i) => !Number.isNaN(i.days)).length
  const materialsChecked = Object.values(user.checklist).reduce((a, arr) => a + arr.length, 0)
  const offerCount = buckets.offer.length

  function handleDrop(col: AppStatus) {
    if (dragId) setStatus(dragId, col)
    setDragId(null)
    setOverCol(null)
  }

  return (
    <div className="wrap">
      <section className="me-intro">
        <Reveal>
          <div className="eyebrow" style={{ marginBottom: 24 }}>04 / Me · 我的申请看板</div>
          <h1>
            我的申请看板,<br />
            <em>从待办到 offer。</em>
          </h1>
          <p>
            收藏的院校会按申请进度分到四栏。每张卡片显示最近截止日期、材料清单进度和项目数量；
            点击卡片可展开完整榜单、硕士项目和申请要求，拖拽即可移动状态。
          </p>
        </Reveal>

        <Reveal delay={0.06}>
          <div className="me-stats">
            <div>
              <span><Heart size={12} style={{ verticalAlign: '-1px', marginRight: 6 }} />收藏院校</span>
              <b className="num">{likedCount}</b>
            </div>
            <div>
              <span><CalendarClock size={12} style={{ verticalAlign: '-1px', marginRight: 6 }} />含截止日期</span>
              <b className="num">{withDeadline}</b>
            </div>
            <div>
              <span><CheckSquare size={12} style={{ verticalAlign: '-1px', marginRight: 6 }} />已勾材料</span>
              <b className="num">{materialsChecked}</b>
            </div>
            <div>
              <span><Bookmark size={12} style={{ verticalAlign: '-1px', marginRight: 6 }} />收到 offer</span>
              <b className="num">{offerCount}</b>
            </div>
          </div>
        </Reveal>
      </section>

      <section className="me-board">
        {ready && likedCount === 0 ? (
          <div className="empty">
            <Inbox size={26} style={{ marginBottom: 14, color: 'var(--ink-5)' }} />
            <p style={{ fontSize: 15, color: 'var(--ink-3)', marginBottom: 18 }}>
              还没有收藏的院校。去榜单里点亮一颗心，这里就会出现申请卡片。
            </p>
            <Link to="/ranking?src=qs" className="mbtn solid" data-cursor>
              前往榜单 <ArrowRight size={14} />
            </Link>
          </div>
        ) : (
          <div className="board">
            {COLS.map((col) => (
              <div className="col" key={col.key}>
                <div className="col-head">
                  <span className="col-dot" style={{ background: col.dot }} />
                  <span className="col-name">{col.name}</span>
                  <span className="col-count">{buckets[col.key].length}</span>
                </div>
                <div
                  className={`col-body${overCol === col.key ? ' drag-over' : ''}`}
                  onDragOver={(e) => { e.preventDefault(); setOverCol(col.key) }}
                  onDragLeave={(e) => {
                    if (!e.currentTarget.contains(e.relatedTarget as Node)) setOverCol(null)
                  }}
                  onDrop={(e) => { e.preventDefault(); handleDrop(col.key) }}
                >
                  {buckets[col.key].map((it) => {
                    const tone = toneFor(it.days)
                    const prog0 = it.programs[0]
                    const hasProg = it.programs.length > 0
                    const idx = ORDER.indexOf(it.status)
                    const next = idx < ORDER.length - 1 ? ORDER[idx + 1] : null
                    return (
                      <div
                        className={`kcard${dragId === it.uniId ? ' dragging' : ''}`}
                        key={it.uniId}
                        data-cursor
                        draggable
                        onDragStart={(e) => {
                          setDragId(it.uniId)
                          e.dataTransfer.effectAllowed = 'move'
                          e.dataTransfer.setData('text/plain', it.uniId)
                        }}
                        onDragEnd={() => { setDragId(null); setOverCol(null) }}
                        onClick={() => open(it.uniId)}
                      >
                        <div className="kcard-top">
                          <div className="kcard-uni">
                            {it.uniName}
                            <small>{it.uniCountry}</small>
                          </div>
                          {hasProg && it.programs.some((p) => p.verified) && <span className="badge ok">已校对</span>}
                        </div>

                        <div className="kcard-prog">
                          {hasProg ? (prog0.program + (it.programs.length > 1 ? ` 等 ${it.programs.length} 个项目` : '')) : '暂无项目情报'}
                        </div>

                        <div className="kcard-foot">
                          {it.date && <span className="num">{it.date}</span>}
                          {!Number.isNaN(it.days) && <span className={`cd ${tone}`}>{countdownLabel(it.days)}</span>}
                        </div>

                        <div className="kcard-mats">
                          {it.matsTotal > 0 && <span>材料 {it.matsChecked}/{it.matsTotal}</span>}
                          <span>{it.reqCount > 0 ? `要求已抽取 ${it.reqCount}` : '暂无要求情报'}</span>
                        </div>

                        <div className="kcard-status" onClick={(ev) => ev.stopPropagation()}>
                          <select
                            className="field status-sel"
                            value={it.status}
                            data-cursor
                            onChange={(e) => setStatus(it.uniId, e.target.value as AppStatus)}
                          >
                            {STATUS_OPT.map((o) => <option key={o.v} value={o.v}>{o.label}</option>)}
                          </select>
                          {next && (
                            <button
                              className="status-next"
                              data-cursor
                              title={'移到「' + (STATUS_OPT.find((o) => o.v === next)!.label) + '」'}
                              onClick={() => setStatus(it.uniId, next)}
                            >
                              <ChevronRight size={14} />
                            </button>
                          )}
                        </div>

                        <div className="kcard-grip" aria-hidden="true"><GripVertical size={12} /></div>
                      </div>
                    )
                  })}
                  {buckets[col.key].length === 0 && <div className="col-empty">拖到这里</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <div style={{ padding: '20px 0 60px' }}>
        <Link to="/ranking?src=qs" className="mbtn" data-cursor>
          继续在榜单里寻找 <ArrowRight size={14} />
        </Link>
      </div>
    </div>
  )
}
