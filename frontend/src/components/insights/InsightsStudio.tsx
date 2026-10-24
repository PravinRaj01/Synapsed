import { Sparkles } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { Card, CardTitle } from '@/components/ui/Card'
import { inputClass } from '@/components/ui/Field'
import { SUGGESTED_PROMPTS, type PromptChart } from '@/lib/charts'
import { useChartFromPrompt, useOpportunityMatrix, usePresetCharts } from '@/lib/insights'
import { ChartCard } from './ChartCard'
import { OpportunityMatrix } from './OpportunityMatrix'

type Made = PromptChart & { id: number; prompt: string }
let counter = 0

function Failed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Card className="py-10 text-center">
      <p role="alert" className="text-sm text-negative">{message}</p>
      <Button className="mt-3" size="sm" onClick={onRetry}>Try again</Button>
    </Card>
  )
}

/** Ask for a chart in words. The model only picks what to group by and measure; the server runs the query on your data. */
function AskForChart({ campaignId }: { campaignId: string }) {
  const make = useChartFromPrompt(campaignId)
  const [prompt, setPrompt] = useState('')
  const [made, setMade] = useState<Made[]>([])

  async function submit(text: string) {
    const trimmed = text.trim()
    if (trimmed.length < 3 || make.isPending) return
    try {
      const chart = await make.mutateAsync(trimmed)
      setMade((list) => [{ ...chart, id: ++counter, prompt: trimmed }, ...list])
      setPrompt('')
    } catch {
      /* the message is shown from make.error below */
    }
  }
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void submit(prompt)
  }

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent-tint text-accent"><Sparkles className="size-5" aria-hidden /></span>
          <div>
            <CardTitle>Ask for a chart</CardTitle>
            <p className="text-xs text-muted">Describe it in your own words. It is built from your data, never invented.</p>
          </div>
        </div>
        <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-2 sm:flex-row">
          <input aria-label="Describe the chart you want" value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Negative sentiment by segment as a stacked bar" maxLength={300} className={`${inputClass} flex-1`} />
          <Button type="submit" variant="accent" loading={make.isPending} disabled={prompt.trim().length < 3}>Make chart</Button>
        </form>
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="Suggestions">
          {SUGGESTED_PROMPTS.map((s) => (
            <li key={s}>
              <button type="button" disabled={make.isPending} onClick={() => void submit(s)} className="rounded-full bg-inner px-3 py-1.5 text-xs text-ink transition-colors hover:bg-line disabled:opacity-50">
                {s}
              </button>
            </li>
          ))}
        </ul>
        {make.isError && <p role="alert" className="mt-3 rounded-inner bg-negative-tint px-4 py-3 text-sm text-negative">{make.error.message}</p>}
      </Card>
      {made.map((m) => (
        <ChartCard
          key={m.id}
          title={m.title ?? m.spec.title ?? 'Your chart'}
          spec={m.spec}
          result={m.result}
          note={<>You asked: “{m.prompt}”{m.model ? ` · ${m.model}` : ''}</>}
          onRemove={() => setMade((list) => list.filter((x) => x.id !== m.id))}
        />
      ))}
    </div>
  )
}

/** The second tab of the Roadmap page: the opportunity matrix, charts from words, and the standard dashboard. */
export default function InsightsStudio({ campaignId }: { campaignId: string }) {
  const matrix = useOpportunityMatrix(campaignId)
  const presets = usePresetCharts(campaignId)

  return (
    <div className="space-y-4">
      {matrix.isLoading ? (
        <div role="status" aria-label="Loading the matrix" className="h-96 animate-pulse rounded-card bg-card shadow-card" />
      ) : matrix.isError ? (
        <Failed message={matrix.error.message} onRetry={() => matrix.refetch()} />
      ) : matrix.data && matrix.data.points.length > 0 ? (
        <OpportunityMatrix matrix={matrix.data} />
      ) : null}

      <AskForChart campaignId={campaignId} />

      <h2 className="px-1 pt-2 text-base font-semibold text-ink">Dashboard</h2>
      {presets.isLoading ? (
        <div role="status" aria-label="Loading the charts" className="grid gap-4 xl:grid-cols-2">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-80 animate-pulse rounded-card bg-card shadow-card" />)}
        </div>
      ) : presets.isError ? (
        <Failed message={presets.error.message} onRetry={() => presets.refetch()} />
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {presets.data?.map((p) => (
            <ChartCard key={p.key} title={p.title ?? p.key} spec={p.spec} result={p.result} />
          ))}
        </div>
      )}
    </div>
  )
}
