import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  CheckCircle2,
  Clock3,
  ExternalLink,
  FileCheck2,
  GraduationCap,
  Heart,
  Link2,
  Search,
  SlidersHorizontal,
} from 'lucide-react'
import { useData } from '../hooks/useData'
import type { Program, RankingSource } from '../types'
import { RANKING_SOURCES } from '../types'
import Reveal from '../components/Reveal'
import LikeButton from '../components/LikeButton'
import { useDrawer } from '../store/drawer'
import { isLiked, useUser } from '../store/likes'

const SRC_LABEL: Record<RankingSource, string> = {
  qs: 'QS', the: 'THE', arwu: 'ARWU', usnews: 'U.S. News', csrankings: 'CS Rankings',
}
const SRC_YEAR: Record<RankingSource, number> = {
  qs: 2026, the: 2026, arwu: 2025, usnews: 2025, csrankings: 2026,
}

type CoverageFilter = 'all' | 'covered' | 'missing'

const foldSearch = (value: string) => value
  .normalize('NFKD')
  .replace(/[\u0300-\u036f]/g, '')
  .toLowerCase()
  .replace(/[^a-z0-9]+/g, ' ')
  .trim()

function hasRequirement(program: Program): boolean {
  const r = program.requirements
  return Boolean(r.gpa || r.ielts || r.toefl || r.language || r.academic)
}

function programStats(programs: Program[]) {
  return {
    total: programs.length,
    verified: programs.filter((p) => p.verified).length,
    deadlines: programs.reduce((sum, p) => sum + p.deadlines.length, 0),
    requirements: programs.filter(hasRequirement).length,
  }
}

export default function Ranking() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const { open } = useDrawer()
  useUser()
  const src = (params.get('src') as RankingSource) || 'qs'
  const setSrc = (s: RankingSource) => {
    const next = new URLSearchParams(params)
    next.set('src', s)
    setParams(next, { replace: true })
  }

  const [q, setQ] = useState('')
  const [region, setRegion] = useState('')
  const [onlyEuro, setOnlyEuro] = useState(false)
  const [onlyPrograms, setOnlyPrograms] = useState(false)
  const [onlyRequirements, setOnlyRequirements] = useState(false)
  const [coverageFilter, setCoverageFilter] = useState<CoverageFilter>('all')
  const [limit, setLimit] = useState(100)

  const data = useData()
  const {
    rankings,
    index,
    unis,
    europeIds,
    programsByUni,
    canonicalById,
    feature2CoverageByUni,
    ready,
  } = data
  const entries = rankings[src] || []
  const europeSet = useMemo(() => new Set(europeIds), [europeIds])

  const regions = useMemo(() => {
    const s = new Set<string>()
    entries.forEach((e) => {
      const u = unis[e.universityId]
      s.add(u?.region || e.country || '-')
    })
    return Array.from(s).sort()
  }, [entries, unis])

  const filtered = useMemo(() => {
    const ql = foldSearch(q.trim())
    return entries.filter((e) => {
      const u = unis[e.universityId]
      const name = u?.name?.en || e.name
      const reg = u?.region || e.country || '-'
      const canonicalId = canonicalById[e.universityId] || e.universityId
      const progs = programsByUni[e.universityId] || programsByUni[canonicalId] || []
      const stats = programStats(progs)
      const coverage = feature2CoverageByUni[e.universityId] || feature2CoverageByUni[canonicalId]
      const isCovered = coverage?.coverageStatus === 'covered' && coverage.urlCount > 0
      const isMissing = coverage?.coverageStatus === 'missing'
      if (onlyEuro && !europeSet.has(e.universityId)) return false
      if (onlyPrograms && stats.total === 0) return false
      if (onlyRequirements && stats.requirements === 0) return false
      if (coverageFilter === 'covered' && !isCovered) return false
      if (coverageFilter === 'missing' && !isMissing) return false
      if (region && reg !== region) return false
      if (ql && !foldSearch(name).includes(ql) && !foldSearch(e.country).includes(ql)) return false
      return true
    })
  }, [
    entries,
    unis,
    q,
    region,
    onlyEuro,
    onlyPrograms,
    onlyRequirements,
    coverageFilter,
    europeSet,
    programsByUni,
    canonicalById,
    feature2CoverageByUni,
  ])

  const visible = src === 'csrankings' ? filtered : filtered.slice(0, limit)

  return (
    <div className="wrap" style={{ paddingTop: 'calc(var(--nav-h) + 50px)' }}>
      <Reveal>
        <div className="sec-head" style={{ marginBottom: 30 }}>
          <div className="l">
            <span className="no">02 / 排名</span>
            <h2>硕士留学<em>信息账本</em></h2>
          </div>
          <p className="note">
            {SRC_LABEL[src]} {SRC_YEAR[src]} · {ready ? filtered.length : '-'} 所 · 点击任一行展开五榜汇总、硕士项目、申请材料和语言要求。
          </p>
        </div>
      </Reveal>

      <Reveal delay={0.04}>
        <div className="tabs">
          {RANKING_SOURCES.map((s) => (
            <button
              key={s}
              className={`tab${s === src ? ' active' : ''}`}
              data-cursor
              onClick={() => setSrc(s)}
            >
              {SRC_LABEL[s]}
              <span className="yr">{SRC_YEAR[s]}</span>
            </button>
          ))}
        </div>
      </Reveal>

      <Reveal delay={0.08}>
        <div className="toolbar">
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <Search size={14} style={{ position: 'absolute', left: 12, color: 'var(--ink-4)', pointerEvents: 'none' }} />
            <input
              className="field"
              placeholder="搜索院校 / 国家"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ paddingLeft: 34, minWidth: 220 }}
            />
          </div>
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <SlidersHorizontal size={13} style={{ position: 'absolute', left: 12, color: 'var(--ink-4)', pointerEvents: 'none' }} />
            <select className="field" value={region} onChange={(e) => setRegion(e.target.value)} style={{ paddingLeft: 34, paddingRight: 30 }}>
              <option value="">全部地区</option>
              {regions.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <Link2 size={13} style={{ position: 'absolute', left: 12, color: 'var(--ink-4)', pointerEvents: 'none' }} />
            <select
              className="field"
              aria-label="官方硕士目录覆盖筛选"
              value={coverageFilter}
              onChange={(e) => setCoverageFilter(e.target.value as CoverageFilter)}
              style={{ paddingLeft: 34, paddingRight: 30 }}
            >
              <option value="all">全部目录状态</option>
              <option value="covered">已有官方目录</option>
              <option value="missing">待补官方目录</option>
            </select>
          </div>
          <button className={`mbtn${onlyEuro ? ' solid' : ''}`} data-cursor style={{ padding: '9px 16px', fontSize: 12 }} onClick={() => setOnlyEuro((v) => !v)}>
            <Heart size={13} fill={onlyEuro ? 'currentColor' : 'none'} /> 欧洲目标
          </button>
          <button className={`mbtn${onlyPrograms ? ' solid' : ''}`} data-cursor style={{ padding: '9px 16px', fontSize: 12 }} onClick={() => setOnlyPrograms((v) => !v)}>
            <GraduationCap size={13} /> 有项目
          </button>
          <button className={`mbtn${onlyRequirements ? ' solid' : ''}`} data-cursor style={{ padding: '9px 16px', fontSize: 12 }} onClick={() => setOnlyRequirements((v) => !v)}>
            <FileCheck2 size={13} /> 有要求
          </button>
          <div className="spacer" />
          <span className="meta-line">{ready ? filtered.length : '-'} 所 · 显示 {visible.length}</span>
        </div>
      </Reveal>

      {!ready ? (
        <p className="empty">加载中...</p>
      ) : (
        <div className="ledger-scroll" role="region" aria-label="大学排名表" tabIndex={0}>
          <table className="ledger">
          <thead>
            <tr>
              <th>#</th>
              <th>院校</th>
              <th>国家 / 地区</th>
              <th>项目与要求</th>
              <th>官方硕士目录</th>
              <th>跨榜排位</th>
              <th className="c"></th>
            </tr>
          </thead>
          <tbody>
            {visible.map((e, i) => {
              const u = unis[e.universityId]
              const name = u?.name?.en || e.name
              const entry = index.byId[e.universityId]
              const liked = isLiked(e.universityId)
              const canonicalId = canonicalById[e.universityId] || e.universityId
              const stats = programStats(programsByUni[e.universityId] || programsByUni[canonicalId] || [])
              const coverage = feature2CoverageByUni[e.universityId] || feature2CoverageByUni[canonicalId]
              const isCovered = coverage?.coverageStatus === 'covered' && coverage.urlCount > 0
              const isMissing = coverage?.coverageStatus === 'missing'
              const officialUrl = isCovered ? coverage.urls[0] : undefined
              return (
                <Reveal as="tr" key={e.universityId + e.rank} delay={(i % 20) * 0.018} y={16}
                  className={`uni-row${liked ? ' liked' : ''}`}
                  onClick={() => open(e.universityId)}>
                  <td className="rank-no num">{e.rank}</td>
                  <td className="uni-cell">
                    <div className="uni-name">{name}</div>
                    <div className="uni-sub"><span className="flag">{e.country}</span></div>
                  </td>
                  <td><span className="flag">{u?.region || e.country || '-'}</span></td>
                  <td>
                    <div className="program-mini">
                      <span><b>{stats.total}</b> 项目</span>
                      <span><b>{stats.deadlines}</b> 截止日期</span>
                      <span><b>{stats.requirements}</b> 有要求</span>
                      {stats.verified > 0 && <span className="ok"><b>{stats.verified}</b> 已校对</span>}
                    </div>
                  </td>

                  <td>
                    <div className="coverage-mini">
                      <span className={isCovered ? 'covered' : isMissing ? 'missing' : 'outside'}>
                        {isCovered ? <CheckCircle2 size={13} /> : isMissing ? <Clock3 size={13} /> : <Link2 size={13} />}
                        {isCovered ? `${coverage.urlCount} 个 URL` : isMissing ? '待补' : '范围外'}
                      </span>
                      {officialUrl && (
                        <a
                          href={officialUrl}
                          target="_blank"
                          rel="noreferrer"
                          title="打开首个官方硕士项目或目录 URL"
                          aria-label={`打开 ${name} 的首个官方硕士目录`}
                          onClick={(ev) => ev.stopPropagation()}
                        >
                          官网 <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                  </td>

                  <td>
                    <div className="cross-mini">
                      {RANKING_SOURCES.filter((s) => s !== src).map((s) => {
                        const r = entry?.ranks.find((x) => x.source === s)
                        return (
                          <span key={s} className={r && r.rank <= 20 ? 'hi' : ''}>
                            {SRC_LABEL[s]} <b>{r ? r.rank : '-'}</b>
                          </span>
                        )
                      })}
                    </div>
                  </td>
                  <td className="c" onClick={(ev) => ev.stopPropagation()}>
                    <LikeButton universityId={e.universityId} size={28} />
                  </td>
                </Reveal>
              )
            })}
          </tbody>
          </table>
        </div>
      )}

      {ready && src !== 'csrankings' && filtered.length > visible.length && (
        <div style={{ textAlign: 'center', marginTop: 30 }}>
          <button className="mbtn" data-cursor onClick={() => setLimit((l) => l + 100)}>
            再展开 100 所
          </button>
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, marginTop: 40, flexWrap: 'wrap' }}>
        <button className="mbtn" data-cursor onClick={() => navigate('/me')}>前往申请看板</button>
        <button className="mbtn" data-cursor onClick={() => navigate('/')}>回到首页</button>
      </div>
    </div>
  )
}
