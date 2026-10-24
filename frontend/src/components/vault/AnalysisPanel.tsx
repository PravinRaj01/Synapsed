import { CheckCircle2, Loader2, Play, Sparkles, XCircle } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { Chip } from '@/components/ui/Chip'
import { runAnalysis, type AnalysisOutcome } from '@/lib/analysis'
import { useRefreshVault } from '@/lib/vault'
import { applyTrace, type Step } from '@/lib/vaultLogic'

/** Run the analysis on approved sources and show it happening: each step, the batch, then what was found. */
export function AnalysisPanel({ campaignId, waiting }: { campaignId: string; waiting: number }) {
  const refresh = useRefreshVault()
  const [running, setRunning] = useState(false)
  const [steps, setSteps] = useState<Step[]>([])
  const [batch, setBatch] = useState(0)
  const [outcome, setOutcome] = useState<AnalysisOutcome | null>(null)
  const [error, setError] = useState<string | null>(null)
  const controller = useRef<AbortController | null>(null)
  const currentBatch = useRef(0)

  async function start() {
    controller.current = new AbortController()
    setRunning(true)
    setSteps([])
    setOutcome(null)
    setError(null)
    setBatch(1)
    currentBatch.current = 1
    try {
      const result = await runAnalysis(
        campaignId,
        {
          onTrace: (event, b) => {
            setBatch(b)
            const fresh = b !== currentBatch.current // a new batch starts its steps from the top
            currentBatch.current = b
            setSteps((prev) => applyTrace(fresh ? [] : prev, event))
          },
          onBatch: () => void refresh(),
        },
        controller.current.signal,
      )
      setOutcome(result)
      if (result.summary.insights > 0) toast.success(`Found ${result.summary.insights} pain points.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The analysis failed.')
    } finally {
      setRunning(false)
      await refresh()
    }
  }

  const summary = outcome?.summary
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent-tint text-accent">
            <Sparkles className="size-5" aria-hidden />
          </span>
          <div>
            <h2 className="text-base font-semibold text-ink">Analysis</h2>
            <p className="text-sm text-muted">
              {running
                ? `Working through your approved sources${batch > 1 ? ` (batch ${batch})` : ''}…`
                : waiting > 0
                  ? `${waiting} approved ${waiting === 1 ? 'source is' : 'sources are'} ready to be analysed.`
                  : 'Everything approved has been analysed.'}
            </p>
          </div>
        </div>
        {running ? (
          <Button variant="secondary" onClick={() => controller.current?.abort()}>
            Stop after this batch
          </Button>
        ) : (
          <Button variant="accent" disabled={waiting === 0} onClick={start}>
            <Play className="size-4" aria-hidden /> Run analysis
          </Button>
        )}
      </div>

      {steps.length > 0 && (
        <ol className="mt-5 grid gap-2 sm:grid-cols-2" aria-label="Analysis steps">
          {steps.map((s) => (
            <li key={s.node} className="flex items-center gap-2 text-sm text-ink">
              {s.status === 'running' ? <Loader2 className="size-4 animate-spin text-accent" aria-label="In progress" /> : s.status === 'error' ? <XCircle className="size-4 text-negative" aria-label="Failed" /> : <CheckCircle2 className="size-4 text-positive" aria-label="Done" />}
              {s.label}
            </li>
          ))}
        </ol>
      )}

      {error && (
        <p role="alert" className="mt-4 rounded-inner bg-negative-tint px-4 py-3 text-sm text-negative">
          {error}
        </p>
      )}

      {summary && (
        <div className="mt-5 border-t border-line pt-4" role="status">
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="positive">{summary.analysed} {summary.analysed === 1 ? 'source' : 'sources'} analysed</Chip>
            <Chip tone="accent">{summary.insights} pain points</Chip>
            <Chip tone="accent">{summary.new_themes} new {summary.new_themes === 1 ? 'theme' : 'themes'}</Chip>
            {summary.roadmap_created > 0 && <Chip tone="accent">{summary.roadmap_created} roadmap {summary.roadmap_created === 1 ? 'item' : 'items'}</Chip>}
            {summary.failed > 0 && <Chip tone="negative">{summary.failed} failed</Chip>}
          </div>
          {outcome?.stopped === 'stuck' && <p className="mt-3 text-sm text-warning">Some sources could not be read, so the run stopped. They stay approved; you can try again later.</p>}
          {outcome?.stopped === 'cancelled' && <p className="mt-3 text-sm text-muted">Stopped. {summary.remaining} {summary.remaining === 1 ? 'source is' : 'sources are'} still waiting.</p>}
          {summary.errors.length > 0 && (
            <ul className="mt-3 space-y-1 text-xs text-muted">
              {summary.errors.map((e, i) => <li key={i}>{e.error}</li>)}
            </ul>
          )}
        </div>
      )}
    </Card>
  )
}
