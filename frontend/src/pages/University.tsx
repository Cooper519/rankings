import { useMemo } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, ArrowUpRight, ExternalLink } from 'lucide-react'
import { useData } from '../hooks/useData'
import type { Program, RankingSource } from '../types'
import { RANKING_SOURCES } from '../types'
import Reveal from '../components/Reveal'
import LikeButton from '../components/LikeButton'
import ProgramCard, { hasRequirement } from '../components/ProgramCard'

const SRC_LABEL: Record<RankingSource, string> = {
  qs: 'QS', the: 'THE', arwu: 'ARWU', usnews: 'USNews', csrankings: 'CS',
}

function subjectLabel(value?: string): string {
  return value && value !== 'General' ? value : '综合/未分类'
}

export default function University() {
  const { id } = useParams<{ id: string }>()
  const { unis, index, programsByUni, coverageByUni, feature2CoverageByUni, canonicalById, ready } = useData()

  const canonicalId = (id && canonicalById[id]) || id || ''
  const uni = unis[canonicalId]
  const entry = index.byId[canonicalId]
  const coverage = coverageByUni[canonicalId]
  const feature2 = feature2CoverageByUni[canonicalId] || (id ? feature2CoverageByUni[id] : undefined)
  const officialUrls = feature2?.urls || []

  const progs: Program[] = useMemo(
    () => (id && programsByUni[id]) || programsByUni[canonicalId] || [],
    [id, canonicalId, programsByUni],
  )
  const grouped = useMemo(() => {
    const m = new Map<string, Program[]>()
    for (const p of progs) {
      const key = subjectLabel(p.subject)
      if (!m.has(key)) m.set(key, [])
      m.get(key)!.push(p)
    }
    return Array.from(m.entries())
      .map(([subject, list]) => ({
        subject,
        list: list.slice().sort((a, b) => {
          if (a.verified !== b.verified) return a.verified ? -1 : 1
          if (hasRequirement(a) !== hasRequirement(b)) return hasRequirement(a) ? -1 : 1
          return a.program.localeCompare(b.program)
        }),
      }))
      .sort((a, b) => b.list.length - a.list.length || a.subject.localeCompare(b.subject))
  }, [progs])

  if (!ready) return <div className="wrap empty" style={{ paddingTop: 140 }}>加载中...</div>
  if (!uni) {
    return (
      <div className="wrap empty" style={{ paddingTop: 140 }}>
        <p>未找到院校：{id}</p>
        <Link to="/ranking?src=qs" className="mbtn" data-cursor>回到榜单</Link>
      </div>
    )
  }

  const deadlines = progs.reduce((n, p) => n + p.deadlines.length, 0)
  const reqCount = progs.filter(hasRequirement).length
  const verifiedCount = progs.filter((p) => p.verified).length

  return (
    <div className="wrap" style={{ paddingTop: 'calc(var(--nav-h) + 40px)', paddingBottom: 80 }}>
      <Reveal>
        <p style={{ marginBottom: 18 }}>
          <Link to="/ranking?src=qs" className="mbtn" style={{ padding: '6px 14px', fontSize: 11 }} data-cursor>
            <ArrowLeft size={12} /> 返回榜单
          </Link>
        </p>
        <div className="sec-head" style={{ marginBottom: 24 }}>
          <div className="l">
            <span className="no">院校详情</span>
            <h2>{uni.name.en}</h2>
          </div>
          <p className="note">
            <span className="flag">{uni.country} · {uni.region || '-'}</span>{' '}
            {uni.website && (
              <a href={uni.website} target="_blank" rel="noreferrer" data-cursor>
                官网 <ArrowUpRight size={11} style={{ verticalAlign: '-1px' }} />
              </a>
            )}
          </p>
        </div>
        <div className="toolbar" style={{ marginBottom: 30 }}>
          <LikeButton universityId={uni.id} size={30} />
          <span className="pill">{progs.length} 项目</span>
          <span className="pill">{deadlines} 截止日期</span>
          <span className="pill">{reqCount} 有要求</span>
          {verifiedCount > 0 && <span className="badge ok">{verifiedCount} 已校对</span>}
          {coverage && <span className="pill">覆盖度 {coverage.completeness}% · 更新 {coverage.updatedAt}</span>}
        </div>
      </Reveal>

      <Reveal delay={0.05}>
        <div className="sub-h">五榜排名 <span className="line" /></div>
        <table className="cross-table" style={{ maxWidth: 560, marginBottom: 36 }}>
          <tbody>
            {RANKING_SOURCES.map((s) => {
              const r = entry?.ranks.find((x) => x.source === s)
              return (
                <tr key={s}>
                  <th>{SRC_LABEL[s]}</th>
                  <td>
                    {r ? (
                      <>
                        <b style={{ color: 'var(--ink)' }}>#{r.rank}</b>
                        {r.score != null && <span style={{ marginLeft: 12, color: 'var(--ink-3)' }}>{r.score}</span>}
                        <span className="yr">{r.year}</span>
                      </>
                    ) : (
                      <span style={{ color: 'var(--ink-5)' }}>未上榜</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Reveal>

      <Reveal delay={0.08}>
        <div className="sub-h">官方硕士目录 <span className="line" /></div>
        <div className="official-directory" style={{ marginBottom: 36 }}>
          <div className="official-directory-status">
            <span className={`badge ${officialUrls.length > 0 ? 'ok' : 'wait'}`}>
              {officialUrls.length > 0 ? '已覆盖' : feature2 ? '待补' : '范围外'}
            </span>
            <span>{officialUrls.length > 0 ? `${officialUrls.length} 个合格 URL` : '暂无合格 URL'}</span>
          </div>
          {officialUrls.length > 0 && (
            <div className="url-chip-list">
              {officialUrls.map((url, i) => (
                <a className="url-chip" href={url} target="_blank" rel="noreferrer" data-cursor title={url} key={url}>
                  <ExternalLink size={12} /> 官方目录 {i + 1}
                </a>
              ))}
            </div>
          )}
        </div>
      </Reveal>

      <div className="sub-h">硕士项目与申请要求（按学科分组） <span className="line" /></div>
      {grouped.length === 0 ? (
        <div className="empty coverage-empty">
          <p>项目情报正在补齐。</p>
          {coverage?.indexUrl && (
            <a className="src-link" href={coverage.indexUrl} target="_blank" rel="noreferrer" data-cursor>
              <ExternalLink size={12} /> 查看官方项目目录
            </a>
          )}
        </div>
      ) : (
        grouped.map((g, gi) => (
          <Reveal key={g.subject} delay={gi * 0.03}>
            <div style={{ marginBottom: 34 }}>
              <h3 style={{ fontSize: 16, marginBottom: 14 }}>
                {g.subject} <span className="pill" style={{ marginLeft: 8 }}>{g.list.length}</span>
              </h3>
              {g.list.map((p) => <ProgramCard key={p.id} p={p} />)}
            </div>
          </Reveal>
        ))
      )}
    </div>
  )
}
