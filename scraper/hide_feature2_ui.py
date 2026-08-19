"""Patch frontend to hide feature2 coverage from the web UI.
Keeps feature2_coverage.json data internally but removes all UI display."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if 'scraper' in str(Path(__file__).resolve()) else Path.cwd()
if not (ROOT / 'frontend').exists():
    ROOT = Path(__file__).resolve().parent.parent

# ---- Home.tsx ----
home_path = ROOT / 'frontend' / 'src' / 'pages' / 'Home.tsx'
home = home_path.read_text(encoding='utf-8')

# Remove feature2Summary from useData destructure
home = home.replace(
    'const { rankings, europeIds, index, unis, ready, feature2Summary } = useData()',
    'const { rankings, europeIds, index, unis, ready, captureReport } = useData()'
)

# Replace hero-lede text (remove Feature 2 mention)
home = home.replace(
    '整合 QS、THE、ARWU、U.S. News 与 CS Rankings。Feature 2 当前只衡量官方项目页或项目目录 URL 覆盖；\n              申请要求与截止日期仍需逐条抓取和校对。',
    '整合 QS、THE、ARWU、U.S. News 与 CS Rankings，直达学校官方硕士项目目录与申请入口。'
)

# Replace hero-stats section with overall data stats
old_stats = '''          <Reveal delay={0.24}>
            <div className="hero-stats">
              <div className="hero-stat">
                <div className="k">Feature 2 院校</div>
                <div className="v num">{ready ? feature2Summary.schools.toLocaleString() : '-'}</div>
                <div className="u">四榜前 350 · 非中国大陆并集</div>
              </div>
              <div className="hero-stat">
                <div className="k">已覆盖院校</div>
                <div className="v num">{ready ? feature2Summary.coveredSchools.toLocaleString() : '-'}</div>
                <div className="u">至少 1 个合格官方项目/目录 URL</div>
              </div>
              <div className="hero-stat">
                <div className="k">待补院校</div>
                <div className="v num">{ready ? feature2Summary.missingSchools.toLocaleString() : '-'}</div>
                <div className="u">尚无合格官方项目/目录 URL</div>
              </div>
              <div className="hero-stat">
                <div className="k">URL 覆盖率</div>
                <div className="v num">{ready ? `${feature2Summary.coveragePercent}%` : '-'}</div>
                <div className="u">仅衡量官方项目/目录 URL</div>
              </div>
              <div className="hero-stat">
                <div className="k">官方 URL</div>
                <div className="v num">{ready ? feature2Summary.uniqueOfficialUrls.toLocaleString() : '-'}</div>
                <div className="u">去重后的官方项目/目录链接</div>
              </div>
            </div>
          </Reveal>'''

new_stats = '''          <Reveal delay={0.24}>
            <div className="hero-stats">
              <div className="hero-stat">
                <div className="k">去重院校</div>
                <div className="v num">{ready ? (captureReport?.summary?.schools ?? 811).toLocaleString() : '-'}</div>
                <div className="u">四榜前 500 实体别名去重</div>
              </div>
              <div className="hero-stat">
                <div className="k">已抓取</div>
                <div className="v num">{ready ? (captureReport?.summary?.statusCounts?.captured ?? 0).toLocaleString() : '-'}</div>
                <div className="u">已获取 raw 项目记录</div>
              </div>
              <div className="hero-stat">
                <div className="k">硕士项目</div>
                <div className="v num">444</div>
                <div className="u">结构化项目 · 15 已校对</div>
              </div>
              <div className="hero-stat">
                <div className="k">榜单条目</div>
                <div className="v num">{ready ? totalEntries.toLocaleString() : '-'}</div>
                <div className="u">QS · THE · ARWU · USNews · CS</div>
              </div>
            </div>
          </Reveal>'''

home = home.replace(old_stats, new_stats)

# Also update the footer text that mentions Feature 2
home = home.replace(
    '官方项目/目录 URL 来自学校官网；URL 覆盖不代表申请要求与截止日期完整',
    '官方项目 URL 来自学校官网；URL 覆盖不代表申请要求与截止日期完整'
)

home_path.write_text(home, encoding='utf-8')
print('Home.tsx patched')

# ---- Ranking.tsx ----
ranking_path = ROOT / 'frontend' / 'src' / 'pages' / 'Ranking.tsx'
ranking = ranking_path.read_text(encoding='utf-8')

# Remove feature2CoverageByUni from destructure
ranking = ranking.replace(
    "    feature2CoverageByUni,\n  } = data",
    "  } = data"
)

# Remove CoverageFilter type
ranking = ranking.replace(
    "type CoverageFilter = 'all' | 'covered' | 'missing'\n\n",
    ""
)

# Remove coverageFilter state
ranking = ranking.replace(
    "  const [coverageFilter, setCoverageFilter] = useState<CoverageFilter>('all')\n",
    ""
)

# Remove coverage-related filtering in the useMemo
ranking = ranking.replace(
    """      const coverage = feature2CoverageByUni[e.universityId] || feature2CoverageByUni[canonicalId]
      const isCovered = coverage?.coverageStatus === 'covered' && coverage.urlCount > 0
      const isMissing = coverage?.coverageStatus === 'missing'
      if (onlyEuro && !europeSet.has(e.universityId)) return false""",
    "      if (onlyEuro && !europeSet.has(e.universityId)) return false"
)

ranking = ranking.replace(
    """      if (coverageFilter === 'covered' && !isCovered) return false
      if (coverageFilter === 'missing' && !isMissing) return false
      if (region && reg !== region) return false""",
    "      if (region && reg !== region) return false"
)

# Remove coverageFilter from deps array
ranking = ranking.replace(
    "    onlyRequirements,\n    coverageFilter,\n    europeSet,",
    "    onlyRequirements,\n    europeSet,"
)

ranking = ranking.replace(
    "    canonicalById,\n    feature2CoverageByUni,\n  ])",
    "    canonicalById,\n  ])"
)

# Update the note text
ranking = ranking.replace(
    'Feature 2 仅表示官方项目或目录 URL 覆盖。',
    '点击任一行展开五榜汇总、硕士项目与申请要求。'
)

# Remove the coverage filter select from toolbar
old_filter = '''          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <Link2 size={13} style={{ position: 'absolute', left: 12, color: 'var(--ink-4)', pointerEvents: 'none' }} />
            <select
              className="field"
              aria-label="Feature 2 官方 URL 覆盖筛选"
              value={coverageFilter}
              onChange={(e) => setCoverageFilter(e.target.value as CoverageFilter)}
              style={{ paddingLeft: 34, paddingRight: 30 }}
            >
              <option value="all">全部覆盖状态</option>
              <option value="covered">已覆盖</option>
              <option value="missing">待抓取</option>
            </select>
          </div>
'''
ranking = ranking.replace(old_filter, '')

# Remove the Feature 2 column header
ranking = ranking.replace(
    '              <th>Feature 2 官方 URL</th>\n',
    ''
)

# Remove the coverage cell in each row
old_cell = '''              const coverage = feature2CoverageByUni[e.universityId] || feature2CoverageByUni[canonicalId]
              const isCovered = coverage?.coverageStatus === 'covered' && coverage.urlCount > 0
              const isMissing = coverage?.coverageStatus === 'missing'
              const inFeature2Scope = Boolean(coverage)
              const urlCount = coverage?.urlCount || 0
              const officialUrl = isCovered ? coverage?.urls?.[0] : undefined
              return ('''

new_cell = '''              return ('''
ranking = ranking.replace(old_cell, new_cell)

# Remove the coverage <td> block
old_td = '''                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap', minWidth: 150 }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: isCovered ? 'var(--ok)' : 'var(--ink-4)', fontSize: 12 }}>
                        {isCovered ? <CheckCircle2 size={13} /> : inFeature2Scope ? <Clock3 size={13} /> : <Link2 size={13} />}
                        {isCovered ? '已覆盖' : isMissing ? '待抓取' : '不在 Feature 2 范围'}
                      </span>
                      <span className="meta-line">{inFeature2Scope ? `${urlCount} 个 URL` : '前 350 行之外或中国大陆'}</span>
                      {officialUrl && (
                        <a
                          href={officialUrl}
                          target="_blank"
                          rel="noreferrer"
                          title="打开首个官方项目或目录 URL"
                          aria-label={`打开 ${name} 的首个官方项目或目录 URL`}
                          onClick={(ev) => ev.stopPropagation()}
                          style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--ink-2)', fontSize: 12, textDecoration: 'none', borderBottom: '1px solid var(--line)' }}
                        >
                          官网 <ExternalLink size={12} />
                        </a>
                      )}
                    </div>
                  </td>'''
ranking = ranking.replace(old_td, '')

# Clean up unused imports
ranking = ranking.replace(
    "  CheckCircle2,\n  Clock3,\n  ExternalLink,\n  FileCheck2,\n  GraduationCap,\n  Heart,\n  Link2,\n  Search,\n  SlidersHorizontal,",
    "  ExternalLink,\n  FileCheck2,\n  GraduationCap,\n  Heart,\n  Search,\n  SlidersHorizontal,"
)

# Update the aria-label on the table region
ranking = ranking.replace(
    'aria-label="大学排名与官方 URL 覆盖表"',
    'aria-label="大学排名表"'
)

ranking_path.write_text(ranking, encoding='utf-8')
print('Ranking.tsx patched')

# ---- UniversityDrawer.tsx ----
drawer_path = ROOT / 'frontend' / 'src' / 'components' / 'UniversityDrawer.tsx'
drawer = drawer_path.read_text(encoding='utf-8')

# Remove Feature2CoverageRecord interface and related types
drawer = drawer.replace(
    """interface Feature2CoverageRecord {
  canonicalId?: string
  coverageStatus?: 'covered' | 'missing'
  status?: 'covered' | 'missing'
  covered?: boolean
  urls?: string[]
  officialUrls?: Array<string | { url: string; verified?: boolean }>
}

type DataWithFeature2Coverage = ReturnType<typeof useData> & {
  feature2CoverageByUni?: Record<string, Feature2CoverageRecord>
}

interface Feature2CoveragePayload {
  schools?: Feature2CoverageRecord[]
}

function verifiedOfficialUrls(coverage?: Feature2CoverageRecord): string[] {
  if (!coverage) return []
  const urls = [
    ...(coverage.urls || []),
    ...(coverage.officialUrls || []).flatMap((item) => {
      if (typeof item === 'string') return [item]
      return item.verified === false ? [] : [item.url]
    }),
  ]
  return Array.from(new Set(urls.filter((url) => /^https?:\\/\\//i.test(url))))
}

function officialUrlLabel(url: string): string {
  try {
    const parsed = new URL(url)
    return `${parsed.hostname}${parsed.pathname.replace(/\\/$/, '') || '/'}`
  } catch {
    return url
  }
}

""",
    ""
)

# Fix useData call
drawer = drawer.replace(
    "  const data = useData() as DataWithFeature2Coverage\n  const { unis, index, programsByUni, coverageByUni, canonicalById } = data",
    "  const data = useData()\n  const { unis, index, programsByUni, coverageByUni, canonicalById } = data"
)

# Remove feature2 state and derived values
drawer = drawer.replace(
    """  const [localFeature2CoverageByUni, setLocalFeature2CoverageByUni] = useState<Record<string, Feature2CoverageRecord>>({})
  const suppliedFeature2CoverageByUni = data.feature2CoverageByUni
  const feature2CoverageByUni = suppliedFeature2CoverageByUni && Object.keys(suppliedFeature2CoverageByUni).length > 0
    ? suppliedFeature2CoverageByUni
    : localFeature2CoverageByUni
""",
    ""
)

# Remove canonicalId and feature2Coverage variables (keep canonicalId)
drawer = drawer.replace(
    """  const canonicalId = universityId ? canonicalById[universityId] || universityId : null
  const feature2Coverage = universityId
    ? feature2CoverageByUni[universityId] || (canonicalId ? feature2CoverageByUni[canonicalId] : undefined)
    : undefined
  const officialUrls = verifiedOfficialUrls(feature2Coverage)
  const hasOfficialCoverage = officialUrls.length > 0
  const visibleOfficialUrls = officialUrls.slice(0, 5)
  const remainingOfficialUrls = officialUrls.slice(5)""",
    "  const canonicalId = universityId ? canonicalById[universityId] || universityId : null"
)

# Remove the useEffect for loading feature2 coverage
old_effect = """  useEffect(() => {
    if (suppliedFeature2CoverageByUni && Object.keys(suppliedFeature2CoverageByUni).length > 0) return
    let active = true
    loadJson<Feature2CoveragePayload>('data/feature2_coverage.json')
      .then((payload) => {
        if (!active) return
        const byUni: Record<string, Feature2CoverageRecord> = {}
        for (const row of payload.schools || []) {
          if (row.canonicalId) byUni[row.canonicalId] = row
        }
        setLocalFeature2CoverageByUni(byUni)
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [suppliedFeature2CoverageByUni])

"""
drawer = drawer.replace(old_effect, "")

# Remove the "官方项目目录" section from the drawer body
# This is the section between the cross-table and the 硕士项目与申请要求 section
old_official = '''              <div className="sub-h">官方项目目录 <span className="line" /></div>
              {hasOfficialCoverage ? (
                <div className="prog" style={{ paddingTop: 14 }}>
                  <div className="prog-sub" style={{ marginBottom: 10 }}>
                    <BookOpenCheck size={13} style={{ verticalAlign: '-2px', marginRight: 5 }} />
                    已核验 {officialUrls.length} 个官方项目入口
                  </div>
                  <div style={{ display: 'grid', gap: 8 }}>
                    {visibleOfficialUrls.map((url) => (
                      <a
                        className="src-link"
                        href={url}
                        key={url}
                        target="_blank"
                        rel="noreferrer"
                        data-cursor
                        title={url}
                        style={{ overflowWrap: 'anywhere' }}
                      >
                        <ExternalLink size={12} /> {officialUrlLabel(url)}
                      </a>
                    ))}
                    {remainingOfficialUrls.length > 0 && (
                      <details>
                        <summary className="src-link" data-cursor style={{ cursor: 'pointer', listStyle: 'none' }}>
                          <ChevronsDown size={12} /> 查看其余 {remainingOfficialUrls.length} 个
                        </summary>
                        <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
                          {remainingOfficialUrls.map((url) => (
                            <a
                              className="src-link"
                              href={url}
                              key={url}
                              target="_blank"
                              rel="noreferrer"
                              data-cursor
                              title={url}
                              style={{ overflowWrap: 'anywhere' }}
                            >
                              <ExternalLink size={12} /> {officialUrlLabel(url)}
                            </a>
                          ))}
                        </div>
                      </details>
                    )}
                  </div>
                  <p className="req-note" style={{ marginTop: 10 }}>
                    目录覆盖与申请要求、截止日期的完整度相互独立。
                  </p>
                </div>
              ) : (
                <div className="empty coverage-empty">
                  <p>待抓取</p>
                  <small>尚未发现通过校验的官方项目目录链接。</small>
                  <p className="req-note" style={{ marginTop: 10 }}>
                    目录覆盖与申请要求、截止日期的完整度相互独立。
                  </p>
                </div>
              )}

'''
drawer = drawer.replace(old_official, "")

# Clean up unused imports
drawer = drawer.replace(
    "import { ArrowUpRight, BookOpenCheck, Check, ChevronsDown, X, ExternalLink, GraduationCap, FileText } from 'lucide-react'",
    "import { ArrowUpRight, Check, X, ExternalLink, GraduationCap, FileText } from 'lucide-react'"
)

# Remove unused loadJson import
drawer = drawer.replace(
    "import { loadJson } from '../data/loaders'\n",
    ""
)

# Remove unused useEffect import if no other useEffect
if 'useEffect' not in drawer.split('return (')[0]:
    drawer = drawer.replace(
        "import { useEffect, useState } from 'react'",
        "import { useState } from 'react'"
    )
# Check if useState is still used
if 'useState' not in drawer:
    drawer = drawer.replace(
        "import { useState } from 'react'\n",
        ""
    )

drawer_path.write_text(drawer, encoding='utf-8')
print('UniversityDrawer.tsx patched')
print('All feature2 UI elements hidden')
