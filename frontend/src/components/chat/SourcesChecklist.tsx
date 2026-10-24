import { cn } from '@/lib/cn'
import { SOURCE_TYPE_LABEL, type Source } from '@/lib/vaultLogic'

type Props = {
  sources: Source[]
  excluded: Set<string>
  openId: string | null
  onToggle: (id: string) => void
  onAll: () => void
  onNone: () => void
  onOpen: (id: string) => void
}

/** The context checklist: only ticked sources are used to answer. Click a title to read it. */
export function SourcesChecklist({ sources, excluded, openId, onToggle, onAll, onNone, onOpen }: Props) {
  const used = sources.filter((s) => !excluded.has(s.id)).length
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-5 py-3">
        <h2 className="text-sm font-semibold text-ink">Sources to use</h2>
        <p className="text-xs text-muted">
          {used} of {sources.length} ticked
          <span className="mx-1.5">·</span>
          <button type="button" onClick={onAll} className="text-accent hover:underline">All</button>
          <span className="mx-1.5">·</span>
          <button type="button" onClick={onNone} className="text-accent hover:underline">None</button>
        </p>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-line overflow-y-auto">
        {sources.map((s) => (
          <li key={s.id} className={cn('flex items-start gap-3 px-5 py-3', openId === s.id && 'bg-accent-tint/60')}>
            <input type="checkbox" aria-label={`Use ${s.title}`} checked={!excluded.has(s.id)} onChange={() => onToggle(s.id)} className="mt-1 size-4 shrink-0 accent-[var(--accent)]" />
            <div className="min-w-0">
              <button type="button" onClick={() => onOpen(s.id)} className="block max-w-full truncate text-left text-sm font-medium text-ink hover:underline">
                {s.title}
              </button>
              <span className="text-xs text-muted">
                {SOURCE_TYPE_LABEL[s.source_type] ?? s.source_type}
                {s.segment ? ` · ${s.segment}` : ''}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
