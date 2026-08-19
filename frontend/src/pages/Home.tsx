import { Link } from 'react-router-dom'
import { ArrowDown, ArrowUpRight, Database } from 'lucide-react'
import { aggregateRank, normalizeName, useData } from '../hooks/useData'
import type { RankingSource } from '../types'
import Reveal from '../components/Reveal'
import Magnetic from '../components/Magnetic'
import { useDrawer } from '../store/drawer'

const SRC_LABEL: Record<RankingSource, string> = {
  qs: 'QS', the: 'THE', arwu: 'ARWU', usnews: 'USNews', csrankings: 'CS',
}
const SRC_FULL: Record<RankingSource, string> = {
  qs: 'QS World University Rankings',
  the: 'Times Higher Education',
  arwu: 'ShanghaiRanking / ARWU',
  usnews: 'U.S. News Best Global',
  csrankings: 'CS Rankings',
}
const SRC_YEAR: Record<RankingSource, number> = {
  qs: 2026, the: 2026, arwu: 2025, usnews: 2025, csrankings: 2026,
}

export default function Home() {
  const { rankings, europeIds, index, unis, ready, captureReport, uniquePrograms, feature2Summary } = useData()
  const { open } = useDrawer()

  const totalEntries = (['qs', 'the', 'arwu', 'usnews', 'csrankings'] as RankingSource[])
    .reduce((a, s) => a + (rankings[s]?.length || 0), 0)
  const years = '2024-2027'
  const updated = captureReport?.generatedAt
    ? new Date(captureReport.generatedAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : '—'

  const featured = europeIds
    .map((id) => ({ id, entry: index.byId[id], agg: aggregateRank(index.byId[id]) }))
    .filter((x) => x.agg != null && x.entry!.ranks.length >= 2)
    .sort((a, b) => (a.agg! - b.agg!))
    .filter((x, _, arr) => {
      const u = unis[x.id]
      const key = normalizeName(u?.name?.en || x.entry?.name || x.id)
      return arr.findIndex((candidate) => {
        const cu = unis[candidate.id]
        return normalizeName(cu?.name?.en || candidate.entry?.name || candidate.id) === key
      }) === arr.indexOf(x)
    })
    .slice(0, 6)

  return (
    <div>
      <section className="hero">
        <div className="wrap">
          <Reveal>
            <div className="hero-eyebrow">
              <span className="pulse" />
              <span className="eyebrow">RankingSelect · 全球大学排名与硕士项目入口</span>
            </div>
          </Reveal>

          <Reveal delay={0.05}>
            <h1>
              排名之外，<br />
              直达官方项目目录。
            </h1>
          </Reveal>

          <Reveal delay={0.12}>
            <p className="hero-lede">
              整合 QS、THE、ARWU、U.S. News 与 CS Rankings，直达学校官方硕士项目目录与申请入口。
            </p>
          </Reveal>

          <Reveal delay={0.18}>
            <div style={{ display: 'flex', gap: 14, marginTop: 38, flexWrap: 'wrap', alignItems: 'center' }}>
              <Magnetic>
                <Link to="/ranking?src=qs" className="mbtn solid" data-cursor>
                  查看榜单 <ArrowUpRight size={15} />
                </Link>
              </Magnetic>
              <Link to="/me" className="mbtn" data-cursor>
                我的申请看板
              </Link>
              <Link to="/programs" className="mbtn" data-cursor>
                硕士项目库
              </Link>
              <Link to="/data-status" className="mbtn" data-cursor>
                数据状态 <Database size={14} />
              </Link>
            </div>
          </Reveal>

          <Reveal delay={0.24}>
            <div className="hero-stats">
              <div className="hero-stat">
                <div className="k">去重院校</div>
                <div className="v num">{ready ? (captureReport?.summary?.schools ?? 0).toLocaleString() : '-'}</div>
                <div className="u">四榜前 500 实体别名去重</div>
              </div>
              <div className="hero-stat">
                <div className="k">已抓取</div>
                <div className="v num">{ready ? (captureReport?.summary?.statusCounts?.captured ?? 0).toLocaleString() : '-'}</div>
                <div className="u">已获取 raw 项目记录</div>
              </div>
              <div className="hero-stat">
                <div className="k">官方目录</div>
                <div className="v num">{ready ? `${feature2Summary.coveredSchools}/${feature2Summary.schools}` : '-'}</div>
                <div className="u">严格 URL 覆盖 · {ready ? `${feature2Summary.coveragePercent}%` : '-'}</div>
              </div>
              <div className="hero-stat">
                <div className="k">硕士项目</div>
                <div className="v num">{ready ? uniquePrograms.length.toLocaleString() : '-'}</div>
                <div className="u">结构化项目 · {ready ? uniquePrograms.filter(p => p.verified).length : 0} 已校对</div>
              </div>
              <div className="hero-stat">
                <div className="k">榜单条目</div>
                <div className="v num">{ready ? totalEntries.toLocaleString() : '-'}</div>
                <div className="u">QS · THE · ARWU · USNews · CS</div>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      <section className="sec">
        <div className="wrap">
          <Reveal>
            <div className="sec-head">
              <div className="l">
                <span className="no">01 / 榜单</span>
                <h2>五大榜单</h2>
              </div>
              <p className="note">每份榜单保持独立年份与评价口径。进入完整列表后，可按地区筛选并查看院校的官方项目 URL 覆盖状态。</p>
            </div>
          </Reveal>
          <Reveal delay={0.05}>
            <div className="src-grid">
              {(['qs', 'the', 'arwu', 'usnews', 'csrankings'] as RankingSource[]).map((s) => (
                <Link key={s} to={`/ranking?src=${s}`} className="src-card" data-cursor>
                  <div className="abbr">{SRC_LABEL[s]}</div>
                  <div className="full">{SRC_FULL[s]}</div>
                  <div className="meta">
                    <span>条目 <b>{rankings[s]?.length || 0}</b></span>
                    <span>{SRC_YEAR[s]}</span>
                  </div>
                  <span className="bar" />
                </Link>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      <section className="sec">
        <div className="wrap">
          <Reveal>
            <div className="sec-head">
              <div className="l">
                <span className="no">02 / 聚焦</span>
                <h2>欧洲院校优先</h2>
              </div>
              <p className="note">优先展示同时进入多个榜单的欧洲目标院校。点击院校可查看跨榜排名与当前已收录的官方项目入口。</p>
            </div>
          </Reveal>
          <Reveal delay={0.05}>
            <div className="feat">
              {featured.map((f) => {
                const u = unis[f.id]
                if (!u) return null
                return (
                  <div key={f.id} className="feat-card" data-cursor onClick={() => open(f.id)}>
                    <div className="rank num">#{Math.round(f.agg!)}</div>
                    <div className="name">{u.name.en}</div>
                    <div className="ctry">{u.country} · {u.region}</div>
                    <div className="cross">
                      {f.entry!.ranks.map((r, rankIndex) => (
                        <span key={`${r.source}-${r.rank}-${rankIndex}`}>{SRC_LABEL[r.source]} <b>#{r.rank}</b></span>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          </Reveal>
        </div>
      </section>

      <section className="sec">
        <div className="wrap">
          <Reveal>
            <div className="sec-head">
              <div className="l">
                <span className="no">03 / 申请</span>
                <h2>项目资料集中检索</h2>
              </div>
              <p className="note">项目库展示当前已抓取并结构化的申请信息。待校对记录保留官方来源，requirement 与 deadline 请以学校页面为准。</p>
            </div>
          </Reveal>
          <Reveal delay={0.05}>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
              <Link to="/programs" className="mbtn solid" data-cursor>
                打开项目库 <ArrowUpRight size={15} />
              </Link>
              <Link to="/ranking?src=qs" className="mbtn" data-cursor>
                从榜单开始
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      <footer className="foot">
        <div className="wrap">
          <Reveal>
            <div className="big">
              全球大学排名<br />
              与官方项目入口。
            </div>
          </Reveal>
          <Reveal delay={0.05}>
            <div className="meta">
              <b>RankingSelect</b> · 纯前端 · 数据存于本地<br />
              数据来源：QS / THE / ARWU / U.S. News / CS Rankings<br />
              官方项目 URL 来自学校官网；URL 覆盖不代表申请要求与截止日期完整<br />
              更新于 {updated} · 覆盖年份 {years} · 当前榜单条目 {totalEntries.toLocaleString()}
            </div>
          </Reveal>
        </div>
      </footer>

      <div style={{ textAlign: 'center', padding: '0 0 90px' }}>
        <Link to="/ranking?src=qs" className="mbtn" data-cursor style={{ margin: '0 auto' }}>
          查看榜单 <ArrowDown size={14} />
        </Link>
      </div>
    </div>
  )
}
