import { useMemo } from 'react'
import { ArrowRight, Download, ExternalLink, GitCompareArrows } from 'lucide-react'
import { Link } from 'react-router-dom'
import Reveal from '../components/Reveal'
import { useData } from '../hooks/useData'
import { useUser } from '../store/likes'
import type { Program, RankingSource } from '../types'
import { RANKING_SOURCES } from '../types'

const SOURCE_LABEL: Record<RankingSource, string> = {
  qs: 'QS',
  the: 'THE',
  arwu: 'ARWU',
  usnews: 'US News',
  csrankings: 'CS Rankings',
}

function hasRequirement(program: Program): boolean {
  return Object.values(program.requirements || {}).some(Boolean)
}

function downloadCsv(rows: CompareItem[]) {
  const escape = (value: string | number) => `"${String(value).replace(/"/g, '""')}"`
  const header = [
    '院校', '国家', ...RANKING_SOURCES.map((source) => SOURCE_LABEL[source]),
    '项目数', '有截止日期项目', '有要求项目', '已校对项目', '学科', '官网',
  ]
  const body = rows.map((item) => [
    item.name,
    item.country,
    ...RANKING_SOURCES.map((source) => item.ranks[source] ?? ''),
    item.programs.length,
    item.deadlinePrograms,
    item.requirementPrograms,
    item.verifiedPrograms,
    item.subjects.join(' / '),
    item.website,
  ].map(escape).join(','))
  const blob = new Blob(['\ufeff' + [header.map(escape).join(','), ...body].join('\n')], {
    type: 'text/csv;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'rankingselect-university-comparison.csv'
  anchor.click()
  URL.revokeObjectURL(url)
}

interface CompareItem {
  id: string
  name: string
  country: string
  website: string
  programs: Program[]
  ranks: Partial<Record<RankingSource, number>>
  deadlinePrograms: number
  requirementPrograms: number
  verifiedPrograms: number
  subjects: string[]
}

export default function Compare() {
  const { unis, index, programsByUni, canonicalById, ready } = useData()
  const user = useUser()

  const items = useMemo<CompareItem[]>(() => {
    const seen = new Set<string>()
    const result: CompareItem[] = []
    for (const likedId of user.likes) {
      const id = canonicalById[likedId] || likedId
      if (seen.has(id)) continue
      seen.add(id)
      const university = unis[id] || unis[likedId]
      if (!university) continue
      const programs = programsByUni[likedId] || programsByUni[id] || []
      const entry = index.byId[likedId] || index.byId[id]
      result.push({
        id,
        name: university.name.en,
        country: university.country,
        website: university.website,
        programs,
        ranks: Object.fromEntries((entry?.ranks || []).map((rank) => [rank.source, rank.rank])),
        deadlinePrograms: programs.filter((program) => program.deadlines.length > 0).length,
        requirementPrograms: programs.filter(hasRequirement).length,
        verifiedPrograms: programs.filter((program) => program.verified).length,
        subjects: Array.from(new Set(programs.map((program) => program.subject).filter((subject) => subject && subject !== 'General'))).sort(),
      })
      if (result.length === 4) break
    }
    return result
  }, [canonicalById, index.byId, programsByUni, unis, user.likes])

  return (
    <div className="wrap compare-page">
      <Reveal>
        <div className="eyebrow" style={{ marginBottom: 22 }}>04 / 院校对比</div>
        <div className="sec-head compare-head">
          <div className="l">
            <h1>把排名和项目覆盖，<br /><em>放在同一张表里。</em></h1>
          </div>
          <p className="note">按收藏顺序比较前 4 所院校。未知字段保持未知，不用空值推断“无要求”。</p>
        </div>
      </Reveal>

      {!ready ? (
        <div className="empty">加载中...</div>
      ) : items.length === 0 ? (
        <div className="empty compare-empty">
          <GitCompareArrows size={28} />
          <p>还没有可对比的院校。先在榜单或院校详情中收藏 2–4 所学校。</p>
          <Link to="/ranking?src=qs" className="mbtn solid" data-cursor>
            前往榜单 <ArrowRight size={14} />
          </Link>
        </div>
      ) : (
        <>
          <div className="toolbar compare-toolbar">
            <span className="pill">当前 {items.length} / 4 所</span>
            {user.likes.length > 4 && <span className="meta-line">仅展示收藏顺序前四所</span>}
            <button className="mbtn" data-cursor onClick={() => downloadCsv(items)}>
              <Download size={13} /> 导出对比 CSV
            </button>
          </div>
          <Reveal delay={0.04}>
            <div className="compare-scroll">
              <table className="compare-table">
                <thead>
                  <tr>
                    <th>指标</th>
                    {items.map((item) => (
                      <th key={item.id}>
                        <Link to={`/university/${item.id}`} data-cursor>{item.name}</Link>
                        <small>{item.country}</small>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {RANKING_SOURCES.map((source) => (
                    <tr key={source}>
                      <th>{SOURCE_LABEL[source]}</th>
                      {items.map((item) => <td className="num" key={item.id}>{item.ranks[source] ? `#${item.ranks[source]}` : '未上榜'}</td>)}
                    </tr>
                  ))}
                  <tr>
                    <th>硕士项目</th>
                    {items.map((item) => <td className="num" key={item.id}>{item.programs.length}</td>)}
                  </tr>
                  <tr>
                    <th>含截止日期</th>
                    {items.map((item) => <td className="num" key={item.id}>{item.deadlinePrograms}</td>)}
                  </tr>
                  <tr>
                    <th>含申请要求</th>
                    {items.map((item) => <td className="num" key={item.id}>{item.requirementPrograms}</td>)}
                  </tr>
                  <tr>
                    <th>人工校对</th>
                    {items.map((item) => <td className="num" key={item.id}>{item.verifiedPrograms}</td>)}
                  </tr>
                  <tr>
                    <th>已收录学科</th>
                    {items.map((item) => <td key={item.id}>{item.subjects.length ? item.subjects.slice(0, 6).join('、') : '待分类'}</td>)}
                  </tr>
                  <tr>
                    <th>官方入口</th>
                    {items.map((item) => (
                      <td key={item.id}>
                        {item.website ? (
                          <a href={item.website} target="_blank" rel="noreferrer" className="src-link" data-cursor>
                            官网 <ExternalLink size={12} />
                          </a>
                        ) : 'URL 待补'}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </Reveal>
        </>
      )}
    </div>
  )
}
