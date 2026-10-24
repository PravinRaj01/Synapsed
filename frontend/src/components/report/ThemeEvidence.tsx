import { Chip } from '@/components/ui/Chip'
import { SENTIMENT } from '@/lib/report'
import { useThemeDetail } from '@/lib/vault'
import { Loading, RowsSkeleton } from '@/components/ui/Skeleton'

export function ThemeInsights({ themeId, onOpenSource }: { themeId: string; onOpenSource: (id: string) => void }) {
  const { data, isLoading, isError, error } = useThemeDetail(themeId)
  if (isLoading) return <Loading label="Loading pain points"><RowsSkeleton rows={2} /></Loading>
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
