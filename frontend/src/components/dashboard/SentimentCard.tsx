import { Card, CardTitle } from '@/components/ui/Card'
import { cn } from '@/lib/cn'
import { sentimentShares } from '@/lib/onboarding'

const LOOK = {
  positive: { label: 'Positive', bar: 'bg-positive' },
  neutral: { label: 'Neutral', bar: 'bg-muted' },
  negative: { label: 'Negative', bar: 'bg-negative' },
} as const

/** How customers feel, as one stacked bar with a legend (colour is never the only cue: every row has its name and count). */
export function SentimentCard({ sentiment }: { sentiment: Record<string, number> }) {
  const shares = sentimentShares(sentiment)
  const total = shares.reduce((n, s) => n + s.count, 0)
  return (
    <Card className="h-full">
      <CardTitle>Customer sentiment</CardTitle>
      <p className="mt-0.5 text-xs text-muted">{total ? `Across ${total.toLocaleString()} pain points and requests` : 'No insights yet'}</p>
      <div className="mt-5 flex h-3 gap-0.5 overflow-hidden rounded-full bg-inner" role="img" aria-label={shares.map((s) => `${LOOK[s.key].label} ${s.percent}%`).join(', ')}>
        {shares
          .filter((s) => s.count > 0)
          .map((s) => (
            <div key={s.key} className={cn('h-full', LOOK[s.key].bar)} style={{ width: `${s.percent}%` }} title={`${LOOK[s.key].label}: ${s.count} (${s.percent}%)`} />
          ))}
      </div>
      <ul className="mt-5 space-y-3">
        {shares.map((s) => (
          <li key={s.key} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-ink">
              <span className={cn('size-2.5 rounded-full', LOOK[s.key].bar)} aria-hidden />
              {LOOK[s.key].label}
            </span>
            <span className="tabular-nums text-muted">
              <span className="font-medium text-ink">{s.count.toLocaleString()}</span> · {s.percent}%
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}
