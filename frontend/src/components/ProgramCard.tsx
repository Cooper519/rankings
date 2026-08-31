import { Check, ExternalLink, GraduationCap } from 'lucide-react'
import type { Program } from '../types'
import { toggleMaterial, useUser } from '../store/likes'
import CountdownPill from './Countdown'

export function hasRequirement(p: Program): boolean {
  const r = p.requirements
  return Boolean(r.gpa || r.ielts || r.toefl || r.gre || r.gmat || r.language || r.academic)
}

export function feeText(p: Program): string {
  const fees = (p.fees || []).filter((f) => f.amount)
  if (!fees.length) return ''
  return fees
    .map((f) => {
      const amount = Number(f.amount).toLocaleString()
      const period = ['per_year', 'year'].includes(f.period || '')
        ? '/年'
        : ['one_time', 'once'].includes(f.period || '')
          ? '/次'
          : f.period ? '/' + f.period : ''
      const who = f.applicantGroup === 'Non-EU' ? '非EU ' : f.applicantGroup === 'EU' ? 'EU ' : ''
      const label = f.type === 'tuition' ? '学费' : f.type === 'registration' ? '注册费' : (f.type || '费用')
      return `${who}${label} ${f.currency || ''} ${amount}${period}`
    })
    .join(' · ')
}

/** One program row: deadlines, materials checklist, requirements, fees, official source. */
export default function ProgramCard({ p, compact = false }: { p: Program; compact?: boolean }) {
  const user = useUser()
  const checked = user.checklist[p.id] || []
  return (
    <div className="prog">
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

      {!compact && p.sourceUrl && (
        <a className="src-link" href={p.sourceUrl} target="_blank" rel="noreferrer" data-cursor>
          <ExternalLink size={12} /> 官方源{p.verified ? '' : '（待核对）'}
        </a>
      )}
    </div>
  )
}
