import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'

const LINKS = [
  { to: '/', label: '首页', idx: '01', end: true },
  { to: '/ranking', label: '榜单', idx: '02', end: false },
  { to: '/programs', label: '项目', idx: '03', end: false },
  { to: '/compare', label: '对比', idx: '04', end: false },
  { to: '/me', label: '看板', idx: '05', end: false },
  { to: '/data-status', label: '数据状态', idx: '06', end: false },
]

function Clock() {
  const [now, setNow] = useState('')
  useEffect(() => {
    const tick = () => {
      const d = new Date()
      const p = (n: number) => String(n).padStart(2, '0')
      setNow(`${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())} SHA`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [])
  return <span className="nav-clock">{now}</span>
}

export default function Nav() {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  return (
    <header className={`nav${scrolled ? ' scrolled' : ''}`}>
      <div className="wrap">
        <NavLink to="/" className="nav-brand" data-cursor>
          <span className="mark">R</span>
          <span>RankingSelect</span>
          <span className="sub">硕士申请情报</span>
        </NavLink>
        <nav className="nav-links">
          {LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end} data-cursor>
              <span className="idx">{l.idx}</span>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="nav-right">
          <Clock />
        </div>
      </div>
    </header>
  )
}
