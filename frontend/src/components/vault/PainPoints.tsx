import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Card } from '@/components/ui/Card'
import { Chip } from '@/components/ui/Chip'
import { ThemeInsights } from '@/components/report/ThemeEvidence'
import { SENTIMENT } from '@/lib/report'
import { cn } from '@/lib/cn'
import { useThemes } from '@/lib/vault'
import { ListCardSkeleton, Loading } from '@/components/ui/Skeleton'

/** Themes found in the sources, ranked by business impact. Open one to read its pain points and the customers' own words. */
export function PainPoints({ campaignId, onOpenSource }: { campaignId: string; onOpenSource: (id: string) => void }) {
  const { data: themes, isLoading, isError, error, refetch } = useThemes(campaignId)
  const [open, setOpen] = useState<string | null>(null)

  if (isLoading) return <Loading label="Loading themes"><ListCardSkeleton rows={4} /></Loading>
  if (isError) {
    return (
      <Card className="py-10 text-center text-sm text-muted">
        <p role="alert" className="text-negative">{error.message}</p>
        <button type="button" onClick={() => refetch()} className="mt-2 font-medium text-accent hover:underline">Try again</button>
      </Card>
    )
  }
  if (!themes?.length) {
    return (
      <Card className="py-14 text-center">
        <h2 className="text-lg font-semibold text-ink">No pain points yet</h2>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted">Approve some sources and run the analysis. Themes and the customers' own words show up here.</p>
      </Card>
    )
  }
  return (
    <Card className="p-0">
      <ul className="divide-y divide-line">
        {themes.map((t) => {
          const expanded = open === t.id
          return (
            <li key={t.id}>
              <button type="button" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : t.id)} className="flex w-full items-center gap-4 px-6 py-4 text-left hover:bg-inner/60">
                <span className="size-3 shrink-0 rounded-full" style={{ background: t.color }} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-ink">{t.label}</span>
                  {t.description && <span className="block truncate text-xs text-muted">{t.description}</span>}
                </span>
                <span className="hidden shrink-0 text-right text-xs text-muted sm:block">
                  <span className="block text-sm font-medium text-ink tabular-nums">{Math.round(t.business_impact)}</span>impact
                </span>
                <span className="hidden shrink-0 text-right text-xs text-muted sm:block">
                  <span className="block text-sm font-medium text-ink tabular-nums">{t.frequency}</span>{t.frequency === 1 ? 'mention' : 'mentions'}
                </span>
                <Chip tone={SENTIMENT[t.sentiment].tone}>{SENTIMENT[t.sentiment].label}</Chip>
                <ChevronDown className={cn('size-4 shrink-0 text-muted transition-transform', expanded && 'rotate-180')} aria-hidden />
              </button>
              {expanded && (
                <div className="px-6 pb-5">
                  <ThemeInsights themeId={t.id} onOpenSource={onOpenSource} />
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
