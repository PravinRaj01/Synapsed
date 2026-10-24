import { postStream, type SseEvent } from './sse'
import { MAX_BATCHES, shouldContinue, totalSummaries, type RunSummary, type TraceEvent } from './vaultLogic'

export type AnalysisHandlers = {
  /** A step started or finished; `batch` counts from 1. */
  onTrace?: (event: TraceEvent, batch: number) => void
  /** A batch finished. */
  onBatch?: (summary: RunSummary, batch: number) => void
}

export type AnalysisOutcome = { summary: RunSummary; batches: number; stopped: 'finished' | 'stuck' | 'limit' | 'cancelled' }

/**
 * Analyse a campaign's approved sources. The server takes one batch per request, so ask again while sources remain.
 * Stops early, without looping forever, if a batch makes no progress. A refused request (409 already running, 429
 * rate limit) throws the ApiError from the stream; a failed run throws an Error with the server's message.
 */
export async function runAnalysis(
  campaignId: string,
  handlers: AnalysisHandlers = {},
  signal?: AbortSignal,
  stream: (path: string, body: unknown, signal?: AbortSignal) => AsyncGenerator<SseEvent> = postStream,
): Promise<AnalysisOutcome> {
  const summaries: RunSummary[] = []
  for (let batch = 1; batch <= MAX_BATCHES; batch++) {
    if (signal?.aborted) return { summary: totalSummaries(summaries), batches: summaries.length, stopped: 'cancelled' }
    let summary: RunSummary | null = null
    for await (const { event, data } of stream('/api/v1/analyze', { campaign_id: campaignId }, signal)) {
      if (event === 'trace') handlers.onTrace?.(data as TraceEvent, batch)
      else if (event === 'summary') summary = data as RunSummary
      else if (event === 'error') throw new Error((data as { message?: string }).message ?? 'The analysis failed.')
    }
    if (!summary) throw new Error('The connection closed before the analysis finished. Run it again; finished sources are kept.')
    summaries.push(summary)
    handlers.onBatch?.(summary, batch)
    if (!shouldContinue(summary, batch)) {
      const stopped = summary.remaining === 0 ? 'finished' : batch >= MAX_BATCHES ? 'limit' : 'stuck'
      return { summary: totalSummaries(summaries), batches: batch, stopped }
    }
  }
  return { summary: totalSummaries(summaries), batches: summaries.length, stopped: 'limit' }
}
