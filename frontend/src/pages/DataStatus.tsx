import { useMemo, useState } from 'react'
import { Database, ExternalLink, Search } from 'lucide-react'
import type { CaptureSchool, CaptureStatus } from '../types'
import { useData } from '../hooks/useData'
import { useDrawer } from '../store/drawer'
import Reveal from '../components/Reveal'

type StatusFilter = 'all' | CaptureStatus

const STATUS_ORDER: CaptureStatus[] = ['captured', 'checked-no-program', 'blocked', 'needs-review', 'pending']
const STATUS_META: Record<CaptureStatus, { label: string; note: string; className: string }> = {
  captured: { label: '已抓取项目', note: 'raw 中已有可读项目页', className: 'captured' },
  'checked-no-program': { label: '已检查无项目', note: '已保存 manifest，但未发现项目候选', className: 'checked' },
  blocked: { label: '被阻断', note: '访问失败或 WAF 阻断', className: 'blocked' },
  'needs-review': { label: '待核验 / 未抓取', note: '身份核验未完成或尚未进入 raw 抓取', className: 'review' },
  pending: { label: '未开始', note: '没有本地抓取证据', className: 'pending' },
}
const SOURCE_LABEL: Record<string, string> = { qs: 'QS', the: 'THE', arwu: 'ARWU', usnews: 'USN' }
const FIELD_LABEL: Record<string, string> = {
  requirements: '要求',
  deadline: '截止',
  applicationWindow: '窗口',
  documents: '材料',
  language: '语言',
}

function percent(value?: number): string {
  if (value == null) return '-'
  return `${Math.round(value * 100)}%`
}

function rankLabel(school: CaptureSchool): string {
  return school.rankingSources
    .map((source) => {
      const rank = school.ranks[source]?.rank
      return `${SOURCE_LABEL[source] || source.toUpperCase()} ${rank ? `#${rank}` : '-'}`
    })
    .join(' · ')
}

export default function DataStatus() {
  const { captureReport, ready } = useData()
  const { open } = useDrawer()
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [query, setQuery] = useState('')
  const [country, setCountry] = useState('')
  const [hideMainlandChina, setHideMainlandChina] = useState(true)
  const [limit, setLimit] = useState(80)

  const countries = useMemo(
    () => Array.from(new Set(captureReport.schools.map((school) => school.country).filter(Boolean))).sort(),
    [captureReport.schools],
  )
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    return captureReport.schools
      .filter((school) => {
        if (filter !== 'all' && school.captureStatus !== filter) return false
        if (hideMainlandChina && school.mainlandChina) return false
        if (country && school.country !== country) return false
        if (needle && !`${school.name} ${school.country}`.toLocaleLowerCase().includes(needle)) return false
        return true
      })
      .sort((a, b) => {
        const statusDelta = STATUS_ORDER.indexOf(a.captureStatus) - STATUS_ORDER.indexOf(b.captureStatus)
        return statusDelta || a.name.localeCompare(b.name)
      })
  }, [captureReport.schools, country, filter, hideMainlandChina, query])

  const summary = captureReport.summary
  const reviewCount = summary.statusCounts['needs-review'] || 0
  const visible = filtered.slice(0, limit)

  return (
    <div className="wrap data-status-page">
      <section className="data-status-intro">
        <Reveal>
          <div className="eyebrow" style={{ marginBottom: 22 }}>05 / 数据状态 · 离线快照</div>
          <h1>先看证据,<br /><em>再看覆盖。</em></h1>
          <p>
            四大榜单前 500 去重后的 {ready ? summary.schools.toLocaleString() : '-'} 所学校。状态来自本地 raw manifest 与项目证据，官方目录 URL 不会被当作申请要求完成。
            中国大陆学校保留历史本地记录，但不会进入新的学校网站访问队列。
          </p>
        </Reveal>
        <Reveal delay={0.06}>
          <div className="capture-stats">
            {STATUS_ORDER.map((status) => (
              <button
                key={status}
                className={`capture-stat${filter === status ? ' active' : ''}`}
                data-cursor
                onClick={() => { setFilter(filter === status ? 'all' : status); setLimit(80) }}
              >
                <span>{STATUS_META[status].label}</span>
                <b className="num">{summary.statusCounts[status] || 0}</b>
              </button>
            ))}
          </div>
        </Reveal>
      </section>

      <section className="data-status-section">
        <Reveal>
          <div className="sec-head" style={{ marginBottom: 28 }}>
            <div className="l">
              <span className="no">01 / 学校队列</span>
              <h2>逐所核对<em>当前状态</em></h2>
            </div>
            <p className="note">已抓取 {summary.rawProgramCaptured.toLocaleString()} / {summary.rawProgramCandidates.toLocaleString()} 个 raw 项目候选。当前页面不启动网络请求。</p>
          </div>
        </Reveal>

        <Reveal delay={0.04}>
          <div className="toolbar">
            <div className="data-search">
              <Search size={14} />
              <input className="field" placeholder="搜索学校 / 国家" value={query} onChange={(event) => { setQuery(event.target.value); setLimit(80) }} />
            </div>
            <select className="field" value={filter} onChange={(event) => { setFilter(event.target.value as StatusFilter); setLimit(80) }}>
              <option value="all">全部状态</option>
              {STATUS_ORDER.map((status) => <option key={status} value={status}>{STATUS_META[status].label}</option>)}
            </select>
            <select className="field" value={country} onChange={(event) => { setCountry(event.target.value); setLimit(80) }}>
              <option value="">全部国家</option>
              {countries.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <button className={`mbtn${hideMainlandChina ? ' solid' : ''}`} data-cursor onClick={() => { setHideMainlandChina((value) => !value); setLimit(80) }}>
              <Database size={13} /> {hideMainlandChina ? '已隐藏中国大陆' : '显示中国大陆'}
            </button>
          </div>
        </Reveal>

        <div className="capture-list">
          {visible.map((school, idx) => {
            const meta = STATUS_META[school.captureStatus]
            const sourceCoverage = school.engineeringAudit.coverage
            return (
              <article className="capture-row" key={`${school.canonicalId}-${idx}`} data-cursor onClick={() => open(school.canonicalId)}>
                <div className="capture-main">
                  <div className="capture-title-line">
                    <h3>{school.name}</h3>
                    <span className={`capture-badge ${meta.className}`}>{meta.label}</span>
                    {school.mainlandChina && <span className="capture-badge policy">中国大陆跳过新访问</span>}
                  </div>
                  <div className="capture-meta">
                    <span>{school.country}</span>
                    <span>{rankLabel(school)}</span>
                    {school.officialReasonCodes[0] && <span>{school.officialReasonCodes[0]}</span>}
                  </div>
                  <div className="capture-evidence">
                    {school.captureStatus === 'captured' ? (
                      <span>raw 项目 {school.raw.programCaptured.toLocaleString()} / 候选 {school.raw.programCandidates.toLocaleString()}</span>
                    ) : (
                      <span>{meta.note}</span>
                    )}
                    {school.engineeringAudit.programCount > 0 && <span>工程/CS 项目 {school.engineeringAudit.programCount.toLocaleString()}</span>}
                  </div>
                </div>
                <div className="capture-fields">
                  {Object.entries(FIELD_LABEL).map(([key, label]) => (
                    <span key={key} title={`${label}覆盖`}>
                      <i>{label}</i>
                      <b className="num">{percent(sourceCoverage[key]?.coverageRate)}</b>
                    </span>
                  ))}
                </div>
                <ExternalLink size={14} className="capture-open" aria-hidden="true" />
              </article>
            )
          })}
        </div>

        {filtered.length > visible.length && (
          <div className="capture-more">
            <button className="mbtn" data-cursor onClick={() => setLimit((value) => value + 80)}>再展开 80 所</button>
            <span className="meta-line">显示 {visible.length} / {filtered.length}</span>
          </div>
        )}
        {filtered.length === 0 && <div className="empty">没有符合当前筛选条件的学校。</div>}
      </section>

      <section className="data-status-section capture-contract">
        <Reveal>
          <div className="sec-head" style={{ marginBottom: 22 }}>
            <div className="l">
              <span className="no">02 / 字段契约</span>
              <h2>申请证据<em>仍需校对</em></h2>
            </div>
            <p className="note">工程/CS 项目审计只统计有项目 raw 的记录；空白字段是待补证据，不是“无要求”。</p>
          </div>
        </Reveal>
        <div className="contract-grid">
          {Object.entries(summary.applicationAudit?.coverage || {}).map(([key, value]) => (
            <div key={key}>
              <span>{FIELD_LABEL[key] || key}</span>
              <b className="num">{value.coveredCount?.toLocaleString() || 0}</b>
              <small>{percent(value.coverageRate)} 项目有证据</small>
            </div>
          ))}
          <div>
            <span>待人工校对</span>
            <b className="num">{reviewCount}</b>
            <small>学校级身份或官方入口</small>
          </div>
        </div>
      </section>
    </div>
  )
}
