import { useEffect, useRef } from 'react'

/**
 * Cursor-reactive generative field: a slow grid of nodes connected by hairlines,
 * with a parallax distortion well around the pointer. Lightweight 2D canvas.
 */
export default function CanvasField() {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    let w = 0, h = 0, dpr = Math.min(window.devicePixelRatio || 1, 2)
    let ptr = { x: -9999, y: -9999, active: false }
    let raf = 0
    const SPACING = 64
    let nodes: { x: number; y: number; ox: number; oy: number }[] = []

    const build = () => {
      w = canvas.clientWidth; h = canvas.clientHeight
      canvas.width = w * dpr; canvas.height = h * dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      nodes = []
      for (let y = SPACING / 2; y < h + SPACING; y += SPACING) {
        for (let x = SPACING / 2; x < w + SPACING; x += SPACING) {
          nodes.push({ x, y, ox: x, oy: y })
        }
      }
    }
    const onResize = () => build()
    const onMove = (e: MouseEvent) => { ptr.x = e.clientX; ptr.y = e.clientY; ptr.active = true }
    const onLeave = () => { ptr.active = false; ptr.x = -9999; ptr.y = -9999 }

    const draw = () => {
      ctx.clearRect(0, 0, w, h)
      const t = performance.now() * 0.0004
      for (const n of nodes) {
        // gentle ambient drift
        const dx0 = Math.sin(t + n.ox * 0.01) * 4
        const dy0 = Math.cos(t + n.oy * 0.01) * 4
        let nx = n.ox + dx0, ny = n.oy + dy0
        if (ptr.active) {
          const ddx = nx - ptr.x, ddy = ny - ptr.y
          const d2 = ddx * ddx + ddy * ddy
          const R = 170
          if (d2 < R * R) {
            const d = Math.sqrt(d2) || 1
            const f = (1 - d / R) * 26
            nx += (ddx / d) * f
            ny += (ddy / d) * f
          }
        }
        n.x = nx; n.y = ny
      }
      // hairlines between near neighbours
      ctx.lineWidth = 1
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i]
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j]
          const dx = a.x - b.x, dy = a.y - b.y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < SPACING * 1.35) {
            const alpha = (1 - dist / (SPACING * 1.35)) * 0.16
            ctx.strokeStyle = `rgba(20,17,12,${alpha})`
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke()
          }
        }
        // node dot
        let near = 0
        if (ptr.active) {
          const ddx = a.x - ptr.x, ddy = a.y - ptr.y
          near = Math.max(0, 1 - Math.sqrt(ddx * ddx + ddy * ddy) / 220)
        }
        ctx.fillStyle = near > 0 ? `rgba(184,71,42,${0.25 + near * 0.5})` : 'rgba(20,17,12,0.18)'
        const r = near > 0 ? 1.6 + near * 2.4 : 1.1
        ctx.beginPath(); ctx.arc(a.x, a.y, r, 0, Math.PI * 2); ctx.fill()
      }
      raf = requestAnimationFrame(draw)
    }
    build()
    draw()
    window.addEventListener('resize', onResize)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseout', onLeave)
    return () => {
      cancelAnimationFrame(raf)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseout', onLeave)
    }
  }, [])
  return <canvas ref={ref} className="canvas-field" aria-hidden />
}