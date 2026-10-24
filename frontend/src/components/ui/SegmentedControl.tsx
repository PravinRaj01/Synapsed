import { motion } from 'motion/react'
import { useId } from 'react'
import { cn } from '@/lib/cn'

type Option<T extends string> = { value: T; label: string }

/** The Silver / Gold / Platinum pattern: a pale track with a white pill that slides to the active option. */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  className,
}: {
  options: Option<T>[]
  value: T
  onChange: (value: T) => void
  label: string
  className?: string
}) {
  const id = useId()
  return (
    <div role="tablist" aria-label={label} className={cn('inline-flex rounded-full bg-inner p-1', className)}>
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            className={cn('relative rounded-full px-4 py-1.5 text-sm font-medium transition-colors', active ? 'text-ink' : 'text-muted hover:text-ink')}
          >
            {active && (
              <motion.span
                layoutId={`segment-${id}`}
                className="absolute inset-0 rounded-full bg-card shadow-card"
                transition={{ type: 'spring', stiffness: 500, damping: 40 }}
              />
            )}
            <span className="relative">{o.label}</span>
          </button>
        )
      })}
    </div>
  )
}
