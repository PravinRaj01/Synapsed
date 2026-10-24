import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import { Card } from '@/components/ui/Card'
import { Chip } from '@/components/ui/Chip'
import { cn } from '@/lib/cn'
import { SENTIMENT } from '@/lib/report'
import { useWide } from '@/lib/useWide'
import type { ThemeRow } from '@/lib/vault'
import { ThemeInsights } from './ThemeEvidence'

const COLUMNS = 'grid-cols-[2rem_minmax(0,1fr)_9rem_4.5rem_4.5rem_4.5rem_6rem_1.5rem]'

function ImpactBar({ value }: { value: number }) {
  return (
    <span className="flex items-center gap-2" title={`Business impact ${Math.round(value)} of 100`}>
      <span className="h-2 w-20 shrink-0 overflow-hidden rounded-full bg-inner" aria-hidden>
        <span className="block h-full rounded-full bg-accent-gradient" style={{ width: `${Math.max(3, value)}%` }} />
      </span>
      <span className="text-sm font-medium text-ink tabular-nums">{Math.round(value)}</span>
    </span>
  )
}

function Detail({ t, onOpenSource }: { t: ThemeRow; onOpenSource: (id: string) => void }) {
  const requests = t.kinds.feature_request ?? 0
  const problems = t.kinds.pain_point ?? 0
  return (
    <div className="space-y-5 px-6 pb-6">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <Chip>{problems} {problems === 1 ? 'pain point' : 'pain points'}</Chip>
        <Chip tone={requests ? 'accent' : 'neutral'}>{requests} feature {requests === 1 ? 'request' : 'requests'}</Chip>
        {t.segments.map((s) => (
          <Chip key={s.segment_id ?? 'none'}>{s.name} · {s.insights}</Chip>
        ))}
      </div>
      {t.use_cases.length > 0 && (
        <div>
          <h4 className="mb-1.5 text-xs font-medium text-muted">What customers were trying to do</h4>
          <ul className="flex flex-wrap gap-2">
            {t.use_cases.map((u) => (
              <li key={u.use_case} className="rounded-full bg-inner px-3 py-1 text-xs text-ink">
                {u.use_case} <span className="text-muted">· {u.insights}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <h4 className="mb-2 text-xs font-medium text-muted">In the customers' own words</h4>
        <ThemeInsights themeId={t.id} onOpenSource={onOpenSource} />
      </div>
    </div>
  )
}

/** The Problem Space Report: themes ranked, with the numbers that matter. Open one for its pain points and quotes. */
export function ThemesTable({ themes, onOpenSource }: { themes: ThemeRow[]; onOpenSource: (id: string) => void }) {
  const [open, setOpen] = useState<string | null>(null)
  const wide = useWide()
  return (
    <Card className="p-0">
      {wide && (
        <div className={cn('grid items-end gap-4 border-b border-line px-6 py-3 text-xs text-muted', COLUMNS)} aria-hidden>
          <span>#</span>
          <span>Theme</span>
          <span>Business impact</span>
          <span className="text-right">Mentions</span>
          <span className="text-right">Sources</span>
          <span className="text-right">Severity</span>
          <span>Tone</span>
          <span />
        </div>
      )}
      <ul className="divide-y divide-line">
        {themes.map((t, i) => {
          const expanded = open === t.id
          const name = (
            <span className="min-w-0">
              <span className="flex items-center gap-2">
                <span className="size-2.5 shrink-0 rounded-full" style={{ background: t.color }} aria-hidden />
                <span className="truncate text-sm font-medium text-ink">{t.label}</span>
              </span>
              {t.description && <span className="mt-0.5 block truncate text-xs text-muted">{t.description}</span>}
            </span>
          )
          const chevron = <ChevronDown className={cn('size-4 text-muted transition-transform', expanded && 'rotate-180')} aria-hidden />
          return (
            <li key={t.id}>
              <button type="button" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : t.id)} className="w-full px-6 py-4 text-left hover:bg-inner/60">
                {wide ? (
                  <span className={cn('grid items-center gap-4', COLUMNS)}>
                    <span className="text-sm text-muted tabular-nums">{i + 1}</span>
                    {name}
                    <ImpactBar value={t.business_impact} />
                    <span className="text-right text-sm tabular-nums text-ink">{t.frequency}</span>
                    <span className="text-right text-sm tabular-nums text-ink">{t.sources}</span>
                    <span className="text-right text-sm tabular-nums text-ink">{t.average_severity ?? '–'}</span>
                    <Chip tone={SENTIMENT[t.sentiment].tone} className="justify-self-start">{SENTIMENT[t.sentiment].label}</Chip>
                    {chevron}
                  </span>
                ) : (
                  <span className="block">
                    <span className="flex items-start gap-3">
                      <span className="mt-0.5 text-sm text-muted tabular-nums">{i + 1}</span>
                      <span className="min-w-0 flex-1">{name}</span>
                      {chevron}
                    </span>
                    <span className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 pl-7 text-xs text-muted">
                      <ImpactBar value={t.business_impact} />
                      <span>{t.frequency} {t.frequency === 1 ? 'mention' : 'mentions'}</span>
                      <span>{t.sources} {t.sources === 1 ? 'source' : 'sources'}</span>
                      <span>severity {t.average_severity ?? '–'}</span>
                      <Chip tone={SENTIMENT[t.sentiment].tone}>{SENTIMENT[t.sentiment].label}</Chip>
                    </span>
                  </span>
                )}
              </button>
              {expanded && <Detail t={t} onOpenSource={onOpenSource} />}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}
