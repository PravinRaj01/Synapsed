import { describe, expect, it, vi } from 'vitest'
import { runAnalysis } from './analysis'
import type { SseEvent } from './sse'
import type { RunSummary } from './vaultLogic'

const summary = (patch: Partial<RunSummary> = {}): RunSummary => ({ selected: 5, analysed: 5, insights: 10, themed: 10, new_themes: 1, roadmap_created: 1, roadmap_updated: 0, failed: 0, errors: [], remaining: 0, ...patch })

/** A stream function that plays one scripted list of events per call. */
function scripted(...batches: SseEvent[][]) {
  let call = 0
  return vi.fn(async function* () {
    const events = batches[call++] ?? []
    for (const e of events) yield e
  })
}
const trace = (node: string, status = 'running') => ({ event: 'trace', data: { node, status } })

describe('runAnalysis', () => {
  it('runs one batch, reports each step and the summary', async () => {
    const stream = scripted([{ event: 'run', data: { run_id: 'r' } }, trace('extract'), trace('extract', 'done'), { event: 'summary', data: summary() }])
    const steps: string[] = []
    const out = await runAnalysis('c1', { onTrace: (e) => steps.push(`${e.node}:${e.status}`) }, undefined, stream)
    expect(steps).toEqual(['extract:running', 'extract:done'])
    expect(out).toMatchObject({ batches: 1, stopped: 'finished', summary: { analysed: 5, insights: 10 } })
    expect(stream).toHaveBeenCalledWith('/api/v1/analyze', { campaign_id: 'c1' }, undefined)
  })

  it('asks again while sources remain and adds the batches up', async () => {
    const stream = scripted([{ event: 'summary', data: summary({ remaining: 4 }) }], [{ event: 'summary', data: summary({ analysed: 4, insights: 7, remaining: 0 }) }])
    const batches: number[] = []
    const out = await runAnalysis('c1', { onBatch: (_s, b) => batches.push(b) }, undefined, stream)
    expect(stream).toHaveBeenCalledTimes(2)
    expect(batches).toEqual([1, 2])
    expect(out).toMatchObject({ batches: 2, stopped: 'finished', summary: { analysed: 9, insights: 17, remaining: 0 } })
  })

  it('stops, instead of looping, when a batch gets nowhere', async () => {
    const stuck = summary({ analysed: 0, failed: 3, remaining: 3, errors: [{ resource_id: 'x', stage: 'extract', error: 'unreadable' }] })
    const stream = scripted([{ event: 'summary', data: stuck }], [{ event: 'summary', data: stuck }])
    const out = await runAnalysis('c1', {}, undefined, stream)
    expect(stream).toHaveBeenCalledTimes(1)
    expect(out).toMatchObject({ stopped: 'stuck', summary: { failed: 3, remaining: 3 } })
    expect(out.summary.errors[0].error).toBe('unreadable')
  })

  it('stops at the batch limit', async () => {
    const stream = vi.fn(async function* () { yield { event: 'summary', data: summary({ remaining: 9 }) } })
    const out = await runAnalysis('c1', {}, undefined, stream)
    expect(out.stopped).toBe('limit')
    expect(out.batches).toBe(25)
  })

  it('throws the server message when the run fails', async () => {
    const stream = scripted([{ event: 'error', data: { message: 'The analysis failed. Resources that were not finished will be picked up by the next run.' } }])
    await expect(runAnalysis('c1', {}, undefined, stream)).rejects.toThrow('Resources that were not finished')
  })

  it('says so when the connection closes with no summary', async () => {
    await expect(runAnalysis('c1', {}, undefined, scripted([trace('extract')]))).rejects.toThrow('connection closed before the analysis finished')
  })

  it('lets a refused request (already running, rate limited) through unchanged', async () => {
    const refused = { [Symbol.asyncIterator]: () => ({ next: () => Promise.reject(new Error('An analysis is already running for this campaign')) }) }
    const stream = vi.fn(() => refused as unknown as AsyncGenerator<SseEvent>)
    await expect(runAnalysis('c1', {}, undefined, stream)).rejects.toThrow('already running')
  })

  it('does not start another batch once cancelled', async () => {
    const controller = new AbortController()
    const stream = scripted([{ event: 'summary', data: summary({ remaining: 4 }) }], [{ event: 'summary', data: summary() }])
    const out = await runAnalysis('c1', { onBatch: () => controller.abort() }, controller.signal, stream)
    expect(stream).toHaveBeenCalledTimes(1)
    expect(out).toMatchObject({ stopped: 'cancelled', batches: 1 })
  })
})
