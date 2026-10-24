import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Chip } from '@/components/ui/Chip'
import { Field, inputClass } from '@/components/ui/Field'
import { editOf, horizonLabel, iceScore, patchFor, type ItemEdit, type RoadmapItem } from '@/lib/board'
import { useUpdateItem } from '@/lib/roadmap'
import { PrdStudio } from './PrdStudio'

const SCORES: { key: 'impact_score' | 'confidence_score' | 'ease_score'; label: string; hint: string }[] = [
  { key: 'impact_score', label: 'Impact', hint: 'How much it matters to customers' },
  { key: 'confidence_score', label: 'Confidence', hint: 'How sure we are, from the evidence' },
  { key: 'ease_score', label: 'Ease', hint: 'How easy it is to do (10 is a small fix)' },
]

function EditForm({ item, campaignId, onSaved }: { item: RoadmapItem; campaignId: string; onSaved: () => void }) {
  const update = useUpdateItem(campaignId)
  const [edit, setEdit] = useState<ItemEdit>(() => editOf(item))
  const patch = patchFor(item, edit)
  const invalid = !edit.title.trim() || !edit.description.trim()

  async function save() {
    if (!patch) return
    try {
      await update.mutateAsync({ id: item.id, patch })
      toast.success('Saved.')
      onSaved()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'It could not be saved.')
    }
  }

  return (
    <div className="space-y-4">
      <Field label="Title" error={!edit.title.trim() ? 'A title is needed' : undefined}>
        <input className={inputClass} value={edit.title} maxLength={200} onChange={(e) => setEdit({ ...edit, title: e.target.value })} />
      </Field>
      <Field label="Description" error={!edit.description.trim() ? 'A description is needed' : undefined}>
        <textarea className={`${inputClass} h-24 resize-y rounded-inner py-3`} value={edit.description} maxLength={2000} onChange={(e) => setEdit({ ...edit, description: e.target.value })} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-3">
        {SCORES.map((s) => (
          <label key={s.key} className="block text-sm">
            <span className="mb-1 flex items-baseline justify-between px-1">
              <span className="font-medium text-ink">{s.label}</span>
              <span className="tabular-nums text-ink">{edit[s.key]}</span>
            </span>
            <input type="range" min={1} max={10} step={1} value={edit[s.key]} aria-label={s.label} onChange={(e) => setEdit({ ...edit, [s.key]: Number(e.target.value) })} className="w-full accent-[var(--accent)]" />
            <span className="block px-1 text-xs text-muted">{s.hint}</span>
          </label>
        ))}
      </div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm text-muted">
          ICE <strong className="text-ink tabular-nums">{iceScore(edit.impact_score, edit.confidence_score, edit.ease_score)}</strong> of 1000
        </p>
        <div className="flex items-center gap-2">
          {patch && <Button variant="ghost" size="sm" onClick={() => setEdit(editOf(item))}>Undo changes</Button>}
          <Button size="sm" loading={update.isPending} disabled={!patch || invalid} onClick={save}>Save changes</Button>
        </div>
      </div>
    </div>
  )
}

/** A card opened: edit its words and scores, and write its PRD. */
export function ItemDrawer({ item, campaignId, onClose }: { item: RoadmapItem | null; campaignId: string; onClose: () => void }) {
  return (
    <Dialog.Root open={!!item} onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content aria-describedby={undefined} className="fixed inset-y-0 right-0 z-50 flex w-full max-w-2xl flex-col border-l border-line bg-card shadow-lift outline-none">
          {item && (
            <>
              <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
                <div className="min-w-0">
                  <Dialog.Title className="truncate text-base font-semibold text-ink">{item.title}</Dialog.Title>
                  <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                    <Chip tone="accent">{horizonLabel(item.horizon)}</Chip>
                    <span className="flex items-center gap-1.5">
                      <span className="size-2 rounded-full" style={{ background: item.color ?? 'var(--accent)' }} aria-hidden />
                      {item.theme ?? 'No theme'}
                    </span>
                    <span>ICE {item.ice_score}</span>
                  </p>
                </div>
                <Dialog.Close aria-label="Close" className="grid size-9 shrink-0 place-items-center rounded-full text-muted hover:bg-inner hover:text-ink">
                  <X className="size-4" aria-hidden />
                </Dialog.Close>
              </div>
              <div className="flex-1 space-y-8 overflow-y-auto px-6 py-5">
                <EditForm key={`${item.id}:${item.ice_score}:${item.title}`} item={item} campaignId={campaignId} onSaved={() => undefined} />
                <hr className="border-line" />
                <PrdStudio item={item} />
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
