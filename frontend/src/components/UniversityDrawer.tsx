import { AnimatePresence, motion } from 'framer-motion'
import { ArrowUpRight, Check, X, ExternalLink, GraduationCap, FileText } from 'lucide-react'
import type { Program, RankingSource } from '../types'
import { RANKING_SOURCES } from '../types'
import { useData } from '../hooks/useData'
import { toggleMaterial, useUser } from '../store/likes'
import LikeButton from './LikeButton'
import CountdownPill from './Countdown'

const SRC_LABEL: Record<RankingSource, string> = {
  qs: 'QS', the: 'THE', arwu: 'ARWU', usnews: 'USNews', csrankings: 'CS',
}

function hasRequirement(p: Program): boolean {
  return Boolean(p.requirements.ielts || p.requirements.toefl || p.requirements.gpa || p.requirements.gre || p.requirements.gmat || p.requirements.language || p.requirements.academic)
}

function feeText(p: Program): string {
  const fees = (p.fees || []).filter((f) => f.amount)
  if (!fees.length) return ''
  return fees
    .map((f) => {
      const amount = Number(f.amount).toLocaleString()
      const period = ['per_year', 'year'].includes(f.period || '') ? '/年' : ['one_time', 'once'].includes(f.period || '') ? '/次' : f.period ? '/' + f.period : ''
      const who = f.applicantGroup === 'Non-EU' ? '非EU ' : f.applicantGroup === 'EU' ? 'EU ' : ''
      return who + (f.type === 'tuition' ? '学费' : f.type === 'registration' ? '注册费' : (f.type || '费用')) + ' ' + f.currency + ' ' + amount + period
    })
    .join(' · ')
}

export default function UniversityDrawer({
  universityId, onClose,
}: { universityId: string | null; onClose: () => void }) {
  const data = useData()
  const { unis, index, programsByUni, coverageByUni, feature2CoverageByUni, canonicalById } = data
  const user = useUser()
  const uni = universityId ? (unis[canonicalById[universityId]] || unis[universityId]) : null
  const entry = universityId ? (index.byId[canonicalById[universityId]] || index.byId[universityId]) : undefined
  const rawProgs: Program[] = (universityId && programsByUni[universityId]) || []
  const coverage = universityId ? coverageByUni[universityId] : undefined
  const feature2Coverage = universityId
    ? (feature2CoverageByUni[universityId] || feature2CoverageByUni[canonicalById[universityId]])
    : undefined
  const officialUrls = feature2Coverage?.urls || []
  const progs = rawProgs.slice().sort((a, b) => {
    if (a.verified !== b.verified) return a.verified ? -1 : 1
    if (hasRequirement(a) !== hasRequirement(b)) return hasRequirement(a) ? -1 : 1
    return a.program.localeCompare(b.program)
  })

  return (
    <AnimatePresence>
      {uni && (
        <>
          <motion.div
            className="drawer-overlay"
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
            onClick={onClose}
          />
          <motion.aside
            className="drawer"
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'spring', stiffness: 380, damping: 38, mass: 0.9 }}
          >
            <div className="drawer-head">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <button className="drawer-close" onClick={onClose} data-cursor>
                  <X size={14} /> 关闭
                </button>
                <LikeButton universityId={uni.id} />
              </div>
              <h3>{uni.name.en}</h3>
              <div className="d-meta">
                <span className="flag">{uni.country} · {uni.region}</span>
                {uni.website && (
                  <a href={uni.website} target="_blank" rel="noreferrer" data-cursor>
                    官网 <ArrowUpRight size={11} style={{ verticalAlign: '-1px' }} />
                  </a>
                )}
                <span className="pill">{progs.length} 项目情报</span>
              </div>
            </div>

            <div className="drawer-body">
              <div className="sub-h">五榜排名 <span className="line" /></div>
              <table className="cross-table">
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

              <div className="sub-h">官方硕士目录 <span className="line" /></div>
              <div className="official-directory">
                <div className="official-directory-status">
                  <span className={`badge ${officialUrls.length > 0 ? 'ok' : 'wait'}`}>
                    {officialUrls.length > 0 ? '已覆盖' : feature2Coverage ? '待补' : '范围外'}
                  </span>
                  <span>{officialUrls.length > 0 ? `${officialUrls.length} 个合格 URL` : '暂无合格 URL'}</span>
                </div>
                {officialUrls.length > 0 && (
                  <div className="official-directory-links">
                    {officialUrls.slice(0, 6).map((url, index) => (
                      <a
                        className="src-link"
                        href={url}
                        target="_blank"
                        rel="noreferrer"
                        data-cursor
                        title={url}
                        key={url}
                      >
                        <ExternalLink size={12} /> 官方目录 {index + 1}
                      </a>
                    ))}
                    {officialUrls.length > 6 && <small>另有 {officialUrls.length - 6} 个已审核 URL</small>}
                  </div>
                )}
              </div>

              <div className="sub-h">硕士项目与申请要求 <span className="line" /></div>
              {progs.length === 0 ? (
                <div className="empty coverage-empty">
                  <p>{coverage?.status === 'pending' ? '尚未发现项目目录。' : '项目情报正在补齐。'}</p>
                  <small>
                    {coverage ? `覆盖度 ${coverage.completeness}% · 更新 ${coverage.updatedAt}` : '等待加入抓取队列'}
                  </small>
                  {coverage?.indexUrl && (
                    <a className="src-link" href={coverage.indexUrl} target="_blank" rel="noreferrer" data-cursor>
                      <ExternalLink size={12} /> 查看官方项目目录
                    </a>
                  )}
                </div>
              ) : (
                progs.map((p) => {
                  const checked = user.checklist[p.id] || []
                  return (
                    <div className="prog" key={p.id}>
                      <div className="prog-top">
                        <span className="prog-name">{p.program}</span>
                        <span className={`badge ${p.verified ? 'ok' : 'wait'}`}>
                          {p.verified ? '已校对' : '待校对'}
                        </span>
                      </div>
                      <div className="prog-sub">
                        <GraduationCap size={12} style={{ verticalAlign: '-2px', marginRight: 4 }} />
                        {p.subject}{p.dept ? ` · ${p.dept}` : ''}
                      </div>

                      {p.deadlines.length > 0 && (
                        <div style={{ marginTop: 10 }}>
                          {p.deadlines.map((d, i) => (
                            <CountdownPill key={i} date={d.date} round={d.round} applicantGroup={d.applicantGroup} />
                          ))}
                        </div>
                      )}

                      {p.materials.length > 0 && (
                        <div className="mats">
                          {p.materials.map((m) => {
                            const on = checked.includes(m)
                            return (
                              <span
                                key={m}
                                className={`mat${on ? ' checked' : ''}`}
                                data-cursor
                                onClick={() => toggleMaterial(p.id, m)}
                              >
                                <Check size={11} className="chk" style={{ display: on ? 'inline' : 'none', verticalAlign: '-1px' }} />
                                {m}
                              </span>
                            )
                          })}
                        </div>
                      )}

                      <div className={`req-line${hasRequirement(p) ? '' : ' muted-req'}`}>
                        {hasRequirement(p) ? (
                          <>
                            {p.requirements.ielts && <span>IELTS <b>{p.requirements.ielts}</b></span>}
                            {p.requirements.toefl && <span>TOEFL <b>{p.requirements.toefl}</b></span>}
                            {p.requirements.gre && <span>{p.requirements.gre}</span>}
                            {p.requirements.gmat && <span>{p.requirements.gmat}</span>}
                            {p.requirements.gpa && <span>GPA <b>{p.requirements.gpa}</b></span>}
                            {p.requirements.language && <span>语言 <b>{p.requirements.language}</b></span>}
                          </>
                        ) : (
                          <span>暂无已抽取硬性要求，请以官方源为准</span>
                        )}
                      </div>

                      {p.requirements.academic && <p className="req-note">{p.requirements.academic}</p>}

                      {feeText(p) && <p className="req-note">{feeText(p)}</p>}

                      {p.sourceUrl && (
                        <a className="src-link" href={p.sourceUrl} target="_blank" rel="noreferrer" data-cursor>
                          <ExternalLink size={12} /> 官方源{p.verified ? '' : '（待核对）'}
                        </a>
                      )}
                    </div>
                  )
                })
              )}
              <div className="drawer-scroll-hint">
                <FileText size={11} style={{ verticalAlign: '-1px', marginRight: 6 }} />
                {progs.length} 条 · 未校对项目请以官方源为准。
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}
