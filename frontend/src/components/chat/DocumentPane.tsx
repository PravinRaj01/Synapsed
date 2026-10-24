import { FileText } from 'lucide-react'
import type { Focus } from '@/lib/chat'
import { useSourceDetail } from '@/lib/vault'
import { SOURCE_TYPE_LABEL } from '@/lib/vaultLogic'
import { HighlightedText } from '@/components/vault/HighlightedText'

export type OpenDoc = { id: string; focus: Focus | null; key: number }

/** The document being read: its text with highlights, and the quote a footnote pointed at flashing. */
export function DocumentPane({ doc }: { doc: OpenDoc | null }) {
  const { data: source, isLoading, isError, error, refetch } = useSourceDetail(doc?.id ?? null)

  if (!doc) {
    return (
      <div className="grid h-full place-items-center px-8 text-center">
        <div>
          <span className="mx-auto grid size-12 place-items-center rounded-full bg-accent-tint text-accent">
            <FileText className="size-6" aria-hidden />
          </span>
          <h2 className="mt-3 text-base font-semibold text-ink">Read the evidence</h2>
          <p className="mx-auto mt-1 max-w-xs text-sm text-muted">Click a footnote in an answer, or a source in the list, to read it here. The quote behind the answer is highlighted.</p>
        </div>
      </div>
    )
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-5 py-3">
        <h2 className="truncate text-sm font-semibold text-ink">{source?.title ?? 'Loading…'}</h2>
        {source && (
          <p className="text-xs text-muted">
            {SOURCE_TYPE_LABEL[source.source_type] ?? source.source_type}
            {source.segment ? ` · ${source.segment}` : ''}
            {source.language ? ` · ${source.language.toUpperCase()}` : ''}
          </p>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        {isLoading && <div role="status" aria-label="Loading source" className="h-48 animate-pulse rounded-inner bg-inner" />}
        {isError && (
          <p role="alert" className="text-sm text-negative">
            {error.message}{' '}
            <button type="button" onClick={() => refetch()} className="font-medium text-accent underline">Try again</button>
          </p>
        )}
        {source && (
          <>
            {source.highlights.length > 0 && <p className="mb-2 text-xs text-muted">Coloured passages are the quotes behind pain points found in this source.</p>}
            <HighlightedText content={source.content} highlights={source.highlights} focus={doc.focus} focusKey={doc.key} />
          </>
        )}
      </div>
    </div>
  )
}
