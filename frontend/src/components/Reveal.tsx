import { motion, useReducedMotion } from 'framer-motion'
import type { ReactNode } from 'react'

/** Scroll-triggered reveal with clip + rise; respects reduced motion. */
export default function Reveal({
  children, delay = 0, y = 28, className = '', as = 'div', onClick,
}: {
  children: ReactNode; delay?: number; y?: number; className?: string
  as?: 'div' | 'section' | 'li' | 'tr'; onClick?: () => void
}) {
  const reduce = useReducedMotion()
  const MotionTag = motion[as] as typeof motion.div
  if (reduce) return <MotionTag className={className} onClick={onClick}>{children}</MotionTag>
  return (
    <MotionTag
      className={className}
      onClick={onClick}
      initial={{ opacity: 0, y, clipPath: 'inset(0 0 100% 0)' }}
      whileInView={{ opacity: 1, y: 0, clipPath: 'inset(0 0 0% 0)' }}
      viewport={{ once: true, margin: '-8% 0px -8% 0px' }}
      transition={{ duration: 0.8, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </MotionTag>
  )
}