import { animate, motion, useMotionValue, useReducedMotion, useTransform } from 'motion/react'
import { ArrowDownRight, ArrowUpRight, type LucideIcon } from 'lucide-react'
import { useEffect } from 'react'
import { cn } from '@/lib/cn'
import { Chip } from './Chip'

/** A number that counts up from zero the first time it appears (and jumps straight to it for reduced motion). */
export function CountUp({ value, format = (n: number) => Math.round(n).toLocaleString() }: { value: number; format?: (n: number) => string }) {
  const reduced = useReducedMotion()
  const count = useMotionValue(reduced ? value : 0)
  const text = useTransform(count, format)
  useEffect(() => {
    if (reduced) {
      count.set(value)
      return
    }
    const controls = animate(count, value, { duration: 0.9, ease: 'easeOut' })
    return () => controls.stop()
  }, [count, value, reduced])
  return <motion.span>{text}</motion.span>
}

type Props = {
  title: string
  /** A number counts up; a string is shown as is. */
  value: number | string
  /** Percent change against the previous period; omit to hide the chip. */
  change?: number | null
  icon: LucideIcon
  /** The one bold emerald card on a page. */
  hero?: boolean
  hint?: string
  className?: string
}

/** The canonical KPI card: title, big number, change chip, icon. Every page reuses it. */
export function StatsCard({ title, value, change, icon: Icon, hero, hint, className }: Props) {
  const up = (change ?? 0) >= 0
  const Arrow = up ? ArrowUpRight : ArrowDownRight
  return (
    <motion.div
      whileHover={{ y: -5 }}
      transition={{ type: 'spring', stiffness: 400, damping: 30 }}
      className={cn(
        'rounded-card p-6 shadow-card',
        hero ? 'bg-accent-gradient text-white' : 'border border-line bg-card text-ink',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className={cn('text-sm', hero ? 'text-white/80' : 'text-muted')}>{title}</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums">{typeof value === 'number' ? <CountUp value={value} /> : value}</p>
          <div className="mt-2 flex items-center gap-2">
            {change != null && (
              <Chip tone={hero ? 'neutral' : up ? 'positive' : 'negative'} className={hero ? 'bg-white/20 text-white' : undefined}>
                <Arrow className="size-3.5" aria-hidden />
                {Math.abs(change)}%
              </Chip>
            )}
            {hint && <span className={cn('truncate text-xs', hero ? 'text-white/70' : 'text-muted')}>{hint}</span>}
          </div>
        </div>
        <span className={cn('grid size-10 shrink-0 place-items-center rounded-full', hero ? 'bg-white/20' : 'bg-accent-tint text-accent')}>
          <Icon className="size-5" aria-hidden />
        </span>
      </div>
    </motion.div>
  )
}
