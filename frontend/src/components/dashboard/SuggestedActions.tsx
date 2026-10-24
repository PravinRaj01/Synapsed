import { AlertTriangle, ArrowRight, CheckCircle2, ClipboardCheck, Sparkles } from 'lucide-react'
import { Link } from 'react-router'
import { Card, CardTitle } from '@/components/ui/Card'
import { cn } from '@/lib/cn'
import type { SuggestedAction } from '@/lib/onboarding'

const ICON = { accent: Sparkles, warning: ClipboardCheck, negative: AlertTriangle, positive: CheckCircle2 }
const TINT = {
  accent: 'bg-accent-tint text-accent',
  warning: 'bg-warning-tint text-warning',
  negative: 'bg-negative-tint text-negative',
  positive: 'bg-positive-tint text-positive',
}

/** What to do next, from the state of the campaign. */
export function SuggestedActions({ actions }: { actions: SuggestedAction[] }) {
  return (
    <Card className="h-full">
      <CardTitle>Suggested actions</CardTitle>
      {actions.length === 0 ? (
        <p className="mt-6 text-center text-sm text-muted">You are all caught up.</p>
      ) : (
        <ul className="mt-4 space-y-2">
          {actions.map((a) => {
            const Icon = ICON[a.tone]
            return (
              <li key={a.id}>
                <Link to={a.to} className="group flex items-center gap-3 rounded-inner p-3 transition-colors hover:bg-inner">
                  <span className={cn('grid size-9 shrink-0 place-items-center rounded-full', TINT[a.tone])}>
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-ink">{a.title}</span>
                    <span className="block truncate text-xs text-muted">{a.detail}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-accent">
                    {a.cta}
                    <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
