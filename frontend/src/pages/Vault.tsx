import { BookOpenCheck, Check, Search, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { AddSources } from '@/components/vault/AddSources'
import { AnalysisPanel } from '@/components/vault/AnalysisPanel'
import { PainPoints } from '@/components/vault/PainPoints'
import { SourcesTable } from '@/components/vault/SourcesTable'
import { SourceViewer } from '@/components/vault/SourceViewer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { inputClass } from '@/components/ui/Field'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useCampaigns } from '@/lib/campaigns'
import { runForEach, useApprove, useBulkSegment, useReject, useSegments, useSources } from '@/lib/vault'
import { awaitingAnalysis, countByStatus, filterSources, NO_FILTER, SOURCE_TYPE_LABEL, type SourceFilter } from '@/lib/vaultLogic'
import { useCampaign } from '@/stores/campaign'

type Tab = 'sources' | 'pain'

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`
}

export default function Vault() {
  const campaigns = useCampaigns()
  const { campaignId } = useCampaign()
  const campaign = campaigns.data?.find((c) => c.id === campaignId) ?? campaigns.data?.[0]
  const sources = useSources(campaign?.id)
  const segments = useSegments(campaign?.id)
  const approve = useApprove()
  const reject = useReject()
  const bulkSegment = useBulkSegment(campaign?.id ?? '')

  const [tab, setTab] = useState<Tab>('sources')
  const [filter, setFilter] = useState<SourceFilter>(NO_FILTER)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState<Set<string>>(new Set())
  const [openId, setOpenId] = useState<string | null>(null)
  const [progress, setProgress] = useState<string | null>(null)

  const all = useMemo(() => sources.data ?? [], [sources.data])
  const counts = countByStatus(all)
  const visible = useMemo(() => filterSources(all, filter), [all, filter])
  const types = useMemo(() => [...new Set(all.map((s) => s.source_type))].sort(), [all])
  const chosen = visible.filter((s) => selected.has(s.id))
  const chosenStaged = chosen.filter((s) => s.status === 'staged')

  const markBusy = (id: string, on: boolean) =>
    setBusy((prev) => {
      const next = new Set(prev)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })

  async function single(id: string, run: () => Promise<unknown>, done: string) {
    markBusy(id, true)
    try {
      await run()
      toast.success(done)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Something went wrong.')
    } finally {
      markBusy(id, false)
    }
  }

  async function bulk(verb: 'Approve' | 'Reject') {
    const ids = chosenStaged.map((s) => s.id)
    const action = verb === 'Approve' ? approve.mutateAsync : reject.mutateAsync
    setProgress(`${verb === 'Approve' ? 'Approving' : 'Rejecting'} 0 of ${ids.length}…`)
    const result = await runForEach(ids, action, (done, total) => setProgress(`${verb === 'Approve' ? 'Approving' : 'Rejecting'} ${done} of ${total}…`))
    setProgress(null)
    setSelected(new Set())
    if (result.done.length) toast.success(`${verb === 'Approve' ? 'Approved' : 'Rejected'} ${plural(result.done.length, 'source')}.`)
    if (result.failed.length) toast.error(result.stoppedEarly ? `${result.failed[0].message} ${plural(result.failed.length, 'source was', 'sources were')} not done.` : `${plural(result.failed.length, 'source')} could not be ${verb === 'Approve' ? 'approved' : 'rejected'}: ${result.failed[0].message}`)
  }

  async function setSegment(segmentId: string) {
    try {
      const r = await bulkSegment.mutateAsync({ ids: chosen.map((s) => s.id), segmentId: segmentId === 'none' ? null : segmentId })
      toast.success(`Segment set on ${plural(r.updated, 'source')}${r.rescored ? '. Impact scores were recalculated.' : '.'}`)
      setSelected(new Set())
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'The segment could not be set.')
    }
  }

  const header = <PageHeader title="Knowledge Vault" subtitle="Upload, review and approve the sources your analysis is built on." actions={campaign && <AddSources campaignId={campaign.id} segments={segments.data ?? []} />} />

  if (campaigns.isLoading) return <>{header}<div role="status" aria-label="Loading" className="h-64 animate-pulse rounded-card bg-card shadow-card" /></>
  if (campaigns.isError) {
    return (
      <>
        {header}
        <Card className="py-14 text-center">
          <p role="alert" className="text-sm text-negative">{campaigns.error.message}</p>
          <Button className="mt-4" onClick={() => campaigns.refetch()}>Try again</Button>
        </Card>
      </>
    )
  }
  if (!campaign) {
    return (
      <>
        {header}
        <Card className="py-14 text-center text-sm text-muted">Create a campaign first, then add sources to it.</Card>
      </>
    )
  }

  const waiting = awaitingAnalysis(all).length

  return (
    <>
      {header}
      <div className="space-y-4">
        {counts.approved > 0 && <AnalysisPanel campaignId={campaign.id} waiting={waiting} />}

        <SegmentedControl<Tab> label="Vault view" value={tab} onChange={setTab} options={[{ value: 'sources', label: `Sources (${counts.all})` }, { value: 'pain', label: 'Pain points' }]} />

        {tab === 'pain' ? (
          <PainPoints campaignId={campaign.id} onOpenSource={setOpenId} />
        ) : sources.isLoading ? (
          <div role="status" aria-label="Loading sources" className="h-64 animate-pulse rounded-card bg-card shadow-card" />
        ) : sources.isError ? (
          <Card className="py-14 text-center">
            <p role="alert" className="text-sm text-negative">{sources.error.message}</p>
            <Button className="mt-4" onClick={() => sources.refetch()}>Try again</Button>
          </Card>
        ) : all.length === 0 ? (
          <Card className="grid place-items-center gap-3 py-16 text-center">
            <span className="grid size-12 place-items-center rounded-full bg-accent-tint text-accent"><BookOpenCheck className="size-6" aria-hidden /></span>
            <h2 className="text-lg font-semibold text-ink">No sources yet</h2>
            <p className="max-w-md text-sm text-muted">Add interviews, tickets or surveys. Personal details are hidden first, and nothing is used until you approve it.</p>
            <AddSources campaignId={campaign.id} segments={segments.data ?? []} />
          </Card>
        ) : (
          <Card className="p-0">
            <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
              <div className="relative min-w-48 flex-1">
                <Search className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted" aria-hidden />
                <input aria-label="Search sources" placeholder="Search sources" value={filter.query} onChange={(e) => setFilter({ ...filter, query: e.target.value })} className={`${inputClass} pl-10`} />
              </div>
              <SegmentedControl<SourceFilter['status']>
                label="Filter by status"
                value={filter.status}
                onChange={(status) => setFilter({ ...filter, status })}
                options={[{ value: 'all', label: `All ${counts.all}` }, { value: 'staged', label: `To review ${counts.staged}` }, { value: 'approved', label: `Approved ${counts.approved}` }, { value: 'rejected', label: `Rejected ${counts.rejected}` }]}
              />
              {types.length > 1 && (
                <select aria-label="Filter by type" className={`${inputClass} w-auto`} value={filter.type} onChange={(e) => setFilter({ ...filter, type: e.target.value })}>
                  <option value="all">All types</option>
                  {types.map((t) => <option key={t} value={t}>{SOURCE_TYPE_LABEL[t] ?? t}</option>)}
                </select>
              )}
            </div>

            {chosen.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-b border-line bg-accent-tint px-4 py-3 text-sm" role="region" aria-label="Bulk actions">
                <span className="font-medium text-ink">{chosen.length} selected</span>
                {chosenStaged.length > 0 && (
                  <>
                    <Button size="sm" disabled={!!progress} onClick={() => bulk('Approve')}><Check className="size-3.5" aria-hidden /> Approve {chosenStaged.length}</Button>
                    <Button size="sm" variant="secondary" disabled={!!progress} onClick={() => bulk('Reject')}><X className="size-3.5" aria-hidden /> Reject {chosenStaged.length}</Button>
                  </>
                )}
                <select aria-label="Set segment for selected" className="h-8 rounded-full border border-line bg-card px-3 text-xs" value="" disabled={!!progress || bulkSegment.isPending} onChange={(e) => e.target.value && setSegment(e.target.value)}>
                  <option value="">Set segment…</option>
                  <option value="none">No segment</option>
                  {(segments.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
                {progress && <span role="status" className="text-muted">{progress}</span>}
                <button type="button" onClick={() => setSelected(new Set())} className="ml-auto text-xs text-muted hover:text-ink">Clear</button>
              </div>
            )}

            {visible.length === 0 ? (
              <p className="px-6 py-12 text-center text-sm text-muted">No sources match.{' '}
                <button type="button" className="font-medium text-accent hover:underline" onClick={() => setFilter(NO_FILTER)}>Clear filters</button>
              </p>
            ) : (
              <div className="px-4 pb-2">
                <SourcesTable
                  sources={visible}
                  selected={selected}
                  busy={busy}
                  onSelect={setSelected}
                  onOpen={setOpenId}
                  onApprove={(id) => single(id, () => approve.mutateAsync(id), 'Approved and ready to analyse.')}
                  onReject={(id) => single(id, () => reject.mutateAsync(id), 'Rejected.')}
                />
              </div>
            )}
          </Card>
        )}
      </div>
      <SourceViewer id={openId} segments={segments.data ?? []} onClose={() => setOpenId(null)} />
    </>
  )
}
