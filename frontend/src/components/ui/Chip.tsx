import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

export type Tone = 'neutral' | 'accent' | 'positive' | 'negative' | 'warning'

const tones: Record<Tone, string> = {
  neutral: 'bg-inner text-muted',
  accent: 'bg-accent-tint text-accent',
  positive: 'bg-positive-tint text-positive',
  negative: 'bg-negative-tint text-negative',
  warning: 'bg-warning-tint text-warning',
}

/** A small rounded status or change label ("+7%", "Completed", "2 active"). */
export function Chip({ tone = 'neutral', className, ...rest }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', tones[tone], className)}
      {...rest}
    />
  )
}
