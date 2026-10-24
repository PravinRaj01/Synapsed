import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Card } from '@/components/ui/Card'
import { Chip, type Tone } from '@/components/ui/Chip'
import { cn } from '@/lib/cn'
import { useThemeDetail, useThemes, type ThemeRow } from '@/lib/vault'

const SENTIMENT: Record<ThemeRow['sentiment'], { label: string; tone: Tone }> = {
  positive: { label: 'Positive', tone: 'positive' },
  negative: { label: 'Negative', tone: 'negative' },
  neutral: { label: 'Neutral', tone: 'neutral' },
  mixed: { label: 'Mixed', tone: 'warning' },
}

function ThemeInsights({ themeId, onOpenSource }: { themeId: string; onOpenSource: (id: string) => void }) {
  const { data, isLoading, isError, error } = useThemeDetail(themeId)
  if (isLoading) return <div role="status" aria-label="Loading pain points" className="h-24 animate-pulse rounded-inner bg-inner" />
  if (isError) return <p role="alert" className="text-sm text-negative">{error.message}</p>
  return (
    <ul className="space-y-3">
      {data!.insights.map((i) => (
        <li key={i.id} className="rounded-inner bg-inner p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-ink">{i.summary_text}</span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
            <Chip tone={i.kind === 'feature_request' ? 'accent' : 'neutral'}>{i.kind === 'feature_request' ? 'Feature request' : 'Pain point'}</Chip>
            <Chip tone={SENTIMENT[i.sentiment].tone}>{SENTIMENT[i.sentiment].label}</Chip>
            <span>Severity {i.severity}/5</span>
            {i.segment && <span>· {i.segment}</span>}
            {i.use_case && <span>· {i.use_case}</span>}
          </div>
          {i.citations.map((c, k) => (
            <blockquote key={k} className="mt-3 border-l-2 pl-3 text-sm text-ink italic" style={{ borderColor: data!.color }}>
              “{c.text_snippet}”
              <button type="button" onClick={() => onOpenSource(c.resource_id)} className="mt-1 block text-xs text-accent not-italic hover:underline">
                {c.resource_title}
              </button>
            </blockquote>
          ))}
        </li>
      ))}
    </ul>
  )
}

/** Themes found in the sources, ranked by business impact. Open one to read its pain points and the customers' own words. */
export function PainPoints({ campaignId, onOpenSource }: { campaignId: string; onOpenSource: (id: string) => void }) {
  const { data: themes, isLoading, isError, error, refetch } = useThemes(campaignId)
  const [open, setOpen] = useState<string | null>(null)

  if (isLoading) return <div role="status" aria-label="Loading themes" className="h-48 animate-pulse rounded-card bg-card shadow-card" />
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
