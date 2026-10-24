import { CheckCircle2, Clock, FileText, XCircle } from 'lucide-react'
import { Link } from 'react-router'
import { Card, CardTitle } from '@/components/ui/Card'
import { Chip, type Tone } from '@/components/ui/Chip'
import { relativeDay } from '@/lib/dates'
import type { Overview } from '@/lib/onboarding'

const STATUS: Record<string, { label: string; tone: Tone; icon: typeof Clock }> = {
  approved: { label: 'Approved', tone: 'positive', icon: CheckCircle2 },
  staged: { label: 'Awaiting approval', tone: 'warning', icon: Clock },
  rejected: { label: 'Rejected', tone: 'negative', icon: XCircle },
}

/** The latest sources, with where each stands. */
export function RecentActivity({ resources }: { resources: Overview['recent_resources'] }) {
  return (
    <Card className="h-full">
      <div className="flex items-center justify-between gap-3">
        <CardTitle>Recent sources</CardTitle>
        <Link to="/vault" className="text-sm font-medium text-accent hover:underline">
          Open vault
        </Link>
      </div>
      {resources.length === 0 ? (
        <p className="mt-6 text-center text-sm text-muted">Nothing uploaded yet.</p>
      ) : (
        <ul className="mt-4 divide-y divide-line">
          {resources.map((r) => {
            const s = STATUS[r.status] ?? STATUS.staged
            return (
              <li key={r.id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-accent-tint text-accent">
                  <FileText className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-ink">{r.title}</span>
                  <span className="block text-xs text-muted">
                    {relativeDay(r.created_at)} · {r.source_type.replace('_', ' ')}
                    {r.language && r.language !== 'en' ? ` · ${r.language.toUpperCase()}` : ''}
                  </span>
                </span>
                <Chip tone={s.tone}>
                  <s.icon className="size-3.5" aria-hidden />
                  {s.label}
                </Chip>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
