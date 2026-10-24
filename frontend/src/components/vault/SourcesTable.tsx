import { Check, Eye, X } from 'lucide-react'
import { Chip, type Tone } from '@/components/ui/Chip'
import { relativeDay } from '@/lib/dates'
import { useWide } from '@/lib/useWide'
import { SOURCE_TYPE_LABEL, type Source } from '@/lib/vaultLogic'

const STATUS: Record<Source['status'], { label: string; tone: Tone }> = {
  staged: { label: 'Awaiting approval', tone: 'warning' },
  approved: { label: 'Approved', tone: 'positive' },
  rejected: { label: 'Rejected', tone: 'negative' },
}

type Props = {
  sources: Source[]
  selected: Set<string>
  busy: Set<string>
  onSelect: (ids: Set<string>) => void
  onOpen: (id: string) => void
  onApprove: (id: string) => void
  onReject: (id: string) => void
}

/** The sources as a table: tick rows for bulk actions, open one to read it, or approve and reject in place. */
export function SourcesTable({ sources, selected, busy, onSelect, onOpen, onApprove, onReject }: Props) {
  const wide = useWide()
  const allSelected = sources.length > 0 && sources.every((s) => selected.has(s.id))
  const toggle = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onSelect(next)
  }
  if (!wide) {
    // A phone has no room for columns: one card per source, with its actions in reach.
    return (
      <ul className="divide-y divide-line">
        {sources.map((s) => {
          const status = STATUS[s.status]
          return (
            <li key={s.id} className="flex gap-3 py-4">
              <input type="checkbox" aria-label={`Select ${s.title}`} checked={selected.has(s.id)} onChange={() => toggle(s.id)} className="mt-1 size-4 shrink-0 accent-[var(--accent)]" />
              <div className="min-w-0 flex-1">
                <button type="button" onClick={() => onOpen(s.id)} className="block max-w-full truncate text-left text-sm font-medium text-ink">
                  {s.title}
                </button>
                <p className="mt-0.5 text-xs text-muted">
                  {SOURCE_TYPE_LABEL[s.source_type] ?? s.source_type} · {s.segment ?? 'No segment'} · {relativeDay(s.created_at)}
                </p>
                {s.pii_note && <p className="mt-0.5 text-xs text-warning">Check for names before approving</p>}
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Chip tone={status.tone}>{status.label}</Chip>
                  {s.status === 'approved' && <span className="text-xs text-muted">{s.analyzed_at ? 'Analysed' : 'Not analysed yet'}</span>}
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <button type="button" aria-label={`Open ${s.title}`} onClick={() => onOpen(s.id)} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-inner px-3 text-xs font-medium text-ink">
                    <Eye className="size-3.5" aria-hidden /> Read
                  </button>
                  {s.status === 'staged' && (
                    <>
                      <button type="button" aria-label={`Approve ${s.title}`} disabled={busy.has(s.id)} onClick={() => onApprove(s.id)} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-positive-tint px-3 text-xs font-medium text-positive disabled:opacity-50">
                        <Check className="size-3.5" aria-hidden /> Approve
                      </button>
                      <button type="button" aria-label={`Reject ${s.title}`} disabled={busy.has(s.id)} onClick={() => onReject(s.id)} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-negative-tint px-3 text-xs font-medium text-negative disabled:opacity-50">
                        <X className="size-3.5" aria-hidden /> Reject
                      </button>
                    </>
                  )}
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead className="text-xs text-muted">
          <tr className="border-b border-line">
            <th className="w-10 py-3 pr-2 pl-1 font-medium">
              <input type="checkbox" aria-label="Select all sources" checked={allSelected} onChange={() => onSelect(allSelected ? new Set() : new Set(sources.map((s) => s.id)))} className="size-4 accent-[var(--accent)]" />
            </th>
            <th className="py-3 pr-4 font-medium">Source</th>
            <th className="py-3 pr-4 font-medium">Type</th>
            <th className="py-3 pr-4 font-medium">Segment</th>
            <th className="py-3 pr-4 font-medium">Status</th>
            <th className="py-3 pr-1 text-right font-medium">Actions</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => {
            const status = STATUS[s.status]
            const working = busy.has(s.id)
            return (
              <tr key={s.id} className="border-b border-line last:border-0 hover:bg-inner/60">
                <td className="py-3 pr-2 pl-1 align-top">
                  <input type="checkbox" aria-label={`Select ${s.title}`} checked={selected.has(s.id)} onChange={() => toggle(s.id)} className="mt-0.5 size-4 accent-[var(--accent)]" />
                </td>
                <td className="max-w-md py-3 pr-4 align-top">
                  <button type="button" onClick={() => onOpen(s.id)} className="block max-w-full truncate text-left font-medium text-ink hover:underline">
                    {s.title}
                  </button>
                  <span className="mt-0.5 block text-xs text-muted">
                    {relativeDay(s.created_at)} · {s.chars.toLocaleString()} characters{s.language && s.language !== 'en' ? ` · ${s.language.toUpperCase()}` : ''}
                  </span>
                  {s.pii_note && <span className="mt-0.5 block text-xs text-warning">Check for names before approving</span>}
                </td>
                <td className="py-3 pr-4 align-top text-muted">{SOURCE_TYPE_LABEL[s.source_type] ?? s.source_type}</td>
                <td className="py-3 pr-4 align-top text-muted">{s.segment ?? '—'}</td>
                <td className="py-3 pr-4 align-top">
                  <Chip tone={status.tone}>{status.label}</Chip>
                  {s.status === 'approved' && (
                    <span className="mt-1 block text-xs text-muted">{s.analyzed_at ? 'Analysed' : 'Not analysed yet'}</span>
                  )}
                </td>
                <td className="py-3 pr-1 align-top">
                  <div className="flex items-center justify-end gap-1">
                    <button type="button" aria-label={`Open ${s.title}`} onClick={() => onOpen(s.id)} className="grid size-8 place-items-center rounded-full text-muted hover:bg-inner hover:text-ink">
                      <Eye className="size-4" aria-hidden />
                    </button>
                    {s.status === 'staged' && (
                      <>
                        <button type="button" aria-label={`Approve ${s.title}`} disabled={working} onClick={() => onApprove(s.id)} className="grid size-8 place-items-center rounded-full text-positive hover:bg-positive-tint disabled:opacity-50">
                          <Check className="size-4" aria-hidden />
                        </button>
                        <button type="button" aria-label={`Reject ${s.title}`} disabled={working} onClick={() => onReject(s.id)} className="grid size-8 place-items-center rounded-full text-negative hover:bg-negative-tint disabled:opacity-50">
                          <X className="size-4" aria-hidden />
                        </button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
