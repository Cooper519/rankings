import { useRef, type ReactNode } from 'react'
import { motion, useReducedMotion } from 'framer-motion'

/** Magnetic hover wrapper — element eases toward the cursor while hovered. */
export default function Magnetic({
  children, strength = 0.35, className = '',
}: { children: ReactNode; strength?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const reduce = useReducedMotion()
  if (reduce) return <div className={className}>{children}</div>
  return (
    <motion.div
      ref={ref}
      className={className}
      whileHover={{ scale: 1.02 }}
      onPointerMove={(e) => {
        const el = ref.current; if (!el) return
        const r = el.getBoundingClientRect()
        const x = (e.clientX - (r.left + r.width / 2)) * strength
        const y = (e.clientY - (r.top + r.height / 2)) * strength
        el.style.transform = `translate(${x}px,${y}px) scale(1.02)`
      }}
      onPointerLeave={() => { if (ref.current) ref.current.style.transform = '' }}
      style={{ willChange: 'transform' }}
    >
      {children}
    </motion.div>
  )
}