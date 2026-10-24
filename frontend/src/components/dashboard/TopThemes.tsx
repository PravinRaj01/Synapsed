import { motion, useReducedMotion } from 'motion/react'
import { Link } from 'react-router'
import { Card, CardTitle } from '@/components/ui/Card'
import type { Overview } from '@/lib/onboarding'

/** Themes ranked by Business Impact (0-100, relative to the strongest). One series, so one colour; the theme's own colour is the dot. */
export function TopThemes({ themes }: { themes: Overview['top_themes'] }) {
  const reduced = useReducedMotion()
  return (
    <Card className="h-full">
      <div className="flex items-center justify-between gap-3">
        <div>
          <CardTitle>Top themes by business impact</CardTitle>
          <p className="mt-0.5 text-xs text-muted">Customer weight × severity, relative to the strongest theme</p>
        </div>
        <Link to="/roadmap" className="text-sm font-medium text-accent hover:underline">
          Full report
        </Link>
      </div>
      {themes.length === 0 ? (
        <p className="mt-8 text-center text-sm text-muted">Themes appear here once your sources have been analysed.</p>
      ) : (
        <ul className="mt-5 space-y-4">
          {themes.map((t, i) => (
            <li key={t.id} title={`${t.label}: impact ${Math.round(t.business_impact)} of 100, ${t.frequency} mentions`}>
              <div className="mb-1.5 flex items-baseline justify-between gap-3 text-sm">
                <span className="flex min-w-0 items-center gap-2 text-ink">
                  <span className="size-2.5 shrink-0 rounded-full" style={{ background: t.color }} aria-hidden />
                  <span className="truncate">{t.label}</span>
                </span>
                <span className="shrink-0 tabular-nums text-muted">
                  <span className="font-medium text-ink">{Math.round(t.business_impact)}</span> · {t.frequency} {t.frequency === 1 ? 'mention' : 'mentions'}
                </span>
              </div>
              <div className="h-2.5 rounded-full bg-inner" role="img" aria-label={`Impact ${Math.round(t.business_impact)} out of 100`}>
                <motion.div
                  className="h-full rounded-full bg-accent-gradient"
                  initial={{ width: reduced ? `${Math.max(2, t.business_impact)}%` : 0 }}
                  animate={{ width: `${Math.max(2, t.business_impact)}%` }}
                  transition={{ duration: 0.7, delay: i * 0.06, ease: 'easeOut' }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
