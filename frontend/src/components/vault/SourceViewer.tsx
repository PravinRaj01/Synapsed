import * as Dialog from '@radix-ui/react-dialog'
import { Check, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Chip } from '@/components/ui/Chip'
import { inputClass } from '@/components/ui/Field'
import { useApprove, useReject, useSourceDetail, useUpdateSource, type Segment } from '@/lib/vault'
import { SOURCE_TYPE_LABEL } from '@/lib/vaultLogic'
import { HighlightedText } from './HighlightedText'
import { DocumentSkeleton, Loading } from '@/components/ui/Skeleton'

/** A source's text with every quote that backs a pain point highlighted in its theme's colour, plus the actions for it. */
export function SourceViewer({ id, segments, onClose }: { id: string | null; segments: Segment[]; onClose: () => void }) {
  const { data: source, isLoading, isError, error } = useSourceDetail(id)
  const approve = useApprove()
  const reject = useReject()
  const update = useUpdateSource()

  async function act(run: () => Promise<unknown>, done: string) {
    try {
      await run()
      toast.success(done)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Something went wrong.')
    }
  }

  return (
    <Dialog.Root open={!!id} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col border-l border-line bg-card shadow-lift outline-none">
          <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-base font-semibold text-ink">{source?.title ?? 'Source'}</Dialog.Title>
              <Dialog.Description className="text-xs text-muted">
                {source ? `${SOURCE_TYPE_LABEL[source.source_type] ?? source.source_type}${source.language ? ` · ${source.language.toUpperCase()}` : ''} · ${source.content.length.toLocaleString()} characters` : 'Loading…'}
              </Dialog.Description>
            </div>
            <Dialog.Close aria-label="Close" className="grid size-9 shrink-0 place-items-center rounded-full text-muted hover:bg-inner hover:text-ink">
              <X className="size-4" aria-hidden />
            </Dialog.Close>
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-5">
            {isLoading && <Loading label="Loading source"><DocumentSkeleton /></Loading>}
            {isError && <p role="alert" className="text-sm text-negative">{error.message}</p>}
            {source && (
              <>
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <Chip tone={source.status === 'approved' ? 'positive' : source.status === 'staged' ? 'warning' : 'negative'}>
                    {source.status === 'staged' ? 'Awaiting approval' : source.status === 'approved' ? 'Approved' : 'Rejected'}
                  </Chip>
                  {source.analyzed_at && <Chip tone="accent">Analysed</Chip>}
                  {source.pii_redacted && <Chip>Personal details hidden</Chip>}
                </div>
                {source.pii_note && <p className="mb-4 rounded-inner bg-warning-tint px-4 py-3 text-sm text-ink">{source.pii_note}</p>}
                {source.summary && <p className="mb-4 text-sm text-muted">{source.summary}</p>}

                <div className="mb-5 grid gap-3 sm:grid-cols-2">
                  <label className="block text-sm">
                    <span className="mb-1 block px-1 font-medium text-ink">Title</span>
                    <input
                      className={inputClass}
                      key={`${source.id}:${source.title}`}
                      defaultValue={source.title}
                      onBlur={(e) => {
                        const next = e.target.value.trim()
                        if (next && next !== source.title) void act(() => update.mutateAsync({ id: source.id, title: next }), 'Renamed.')
                      }}
                    />
                  </label>
                  <label className="block text-sm">
                    <span className="mb-1 block px-1 font-medium text-ink">Customer segment</span>
                    <select
                      className={inputClass}
                      value={source.segment_id ?? ''}
                      onChange={(e) => act(() => update.mutateAsync({ id: source.id, segment_id: e.target.value || null }), 'Segment updated.')}
                    >
                      <option value="">Not set</option>
                      {segments.map((s) => (
                        <option key={s.id} value={s.id}>{s.name}</option>
                      ))}
                    </select>
                  </label>
                </div>

                {source.highlights.length > 0 && <p className="mb-2 text-xs text-muted">Highlighted passages are the quotes behind pain points found in this source.</p>}
                <HighlightedText content={source.content} highlights={source.highlights} />
              </>
            )}
          </div>

          {source?.status === 'staged' && (
            <div className="flex items-center justify-end gap-2 border-t border-line px-6 py-4">
              <Button variant="secondary" loading={reject.isPending} disabled={approve.isPending} onClick={() => act(() => reject.mutateAsync(source.id).then(onClose), 'Rejected.')}>
                Reject
              </Button>
              <Button loading={approve.isPending} disabled={reject.isPending} onClick={() => act(() => approve.mutateAsync(source.id), 'Approved and ready to analyse.')}>
                <Check className="size-4" aria-hidden /> Approve and embed
              </Button>
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
