import * as Dialog from '@radix-ui/react-dialog'
import { AlertTriangle, CheckCircle2, FileText, Loader2, Plus, Upload, X } from 'lucide-react'
import { useId, useRef, useState, type DragEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { Field, inputClass } from '@/components/ui/Field'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { cn } from '@/lib/cn'
import { noteFile, uploadSource } from '@/lib/upload'
import { useRefreshVault, useResearch, type Segment } from '@/lib/vault'
import { ACCEPT, CHOSEN_TYPES, checkFile, formatBytes, ingestNote, isTable, sourceTypeFor, type ChosenType, type Ingested } from '@/lib/vaultLogic'

type Tab = 'upload' | 'paste' | 'web'
type Item = { id: string; file: File; state: 'ready' | 'sending' | 'done' | 'error'; progress: number; error?: string; results?: Ingested[]; refused?: string }

let counter = 0

function SegmentSelect({ segments, value, onChange }: { segments: Segment[]; value: string; onChange: (v: string) => void }) {
  return (
    <Field label="Customer segment" hint="Who these sources come from. It sets how much their pain points count.">
      <select className={inputClass} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Not set</option>
        {segments.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} (weight {s.weight})
          </option>
        ))}
      </select>
    </Field>
  )
}

function TypeSelect({ value, onChange }: { value: ChosenType; onChange: (v: ChosenType) => void }) {
  return (
    <Field label="What kind of source is it?" hint="Text files are read as interviews unless you say otherwise.">
      <select className={inputClass} value={value} onChange={(e) => onChange(e.target.value as ChosenType)}>
        {CHOSEN_TYPES.map((t) => (
          <option key={t.value} value={t.value}>
            {t.label}
          </option>
        ))}
      </select>
    </Field>
  )
}

function ResultNote({ r }: { r: Ingested }) {
  const note = ingestNote(r)
  return (
    <li className="text-xs">
      <span className="font-medium text-ink">{r.title}</span>
      <span className="text-muted"> · {r.chars.toLocaleString()} characters{r.language ? ` · ${r.language.toUpperCase()}` : ''}</span>
      {note && <span className={cn('mt-0.5 block', note.tone === 'warning' ? 'text-warning' : 'text-muted')}>{note.text}</span>}
    </li>
  )
}

function UploadTab({ campaignId, segments }: { campaignId: string; segments: Segment[] }) {
  const refresh = useRefreshVault()
  const input = useRef<HTMLInputElement>(null)
  const [items, setItems] = useState<Item[]>([])
  const [segmentId, setSegmentId] = useState('')
  const [chosenType, setChosenType] = useState<ChosenType>('')
  const [textColumn, setTextColumn] = useState('')
  const [segmentColumn, setSegmentColumn] = useState('')
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const patch = (id: string, p: Partial<Item>) => setItems((list) => list.map((i) => (i.id === id ? { ...i, ...p } : i)))

  function add(files: FileList | File[]) {
    const fresh: Item[] = Array.from(files).map((file) => ({ id: `f${++counter}`, file, state: 'ready', progress: 0, refused: checkFile(file) ?? undefined }))
    setItems((list) => [...list, ...fresh])
  }

  function drop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    if (e.dataTransfer.files.length) add(e.dataTransfer.files)
  }

  const sendable = items.filter((i) => i.state === 'ready' && !i.refused)
  const hasTable = items.some((i) => isTable(i.file.name))

  async function send() {
    setBusy(true)
    for (const item of sendable) {
      patch(item.id, { state: 'sending', progress: 0 })
      try {
        const out = await uploadSource(item.file, { campaignId, segmentId: segmentId || null, textColumn, segmentColumn, sourceType: sourceTypeFor(item.file.name, chosenType) }, (progress) => patch(item.id, { progress }))
        patch(item.id, { state: 'done', progress: 1, results: out.resources })
      } catch (e) {
        patch(item.id, { state: 'error', error: e instanceof Error ? e.message : 'The upload failed.' })
      }
      await refresh()
    }
    setBusy(false)
  }

  return (
    <div className="space-y-4">
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
        className={cn('grid place-items-center gap-2 rounded-card border-2 border-dashed px-6 py-10 text-center transition-colors', over ? 'border-accent bg-accent-tint' : 'border-line bg-inner')}
      >
        <span className="grid size-11 place-items-center rounded-full bg-accent-tint text-accent">
          <Upload className="size-5" aria-hidden />
        </span>
        <p className="text-sm font-medium text-ink">Drop files here</p>
        <p className="text-xs text-muted">Interviews, tickets, surveys: text, PDF, images, audio, video, CSV or Excel. Up to 50 MB each.</p>
        <Button type="button" variant="secondary" size="sm" onClick={() => input.current?.click()}>
          Choose files
        </Button>
        <input ref={input} type="file" multiple accept={ACCEPT} aria-label="Choose files" className="hidden" onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = '' }} />
      </div>

      {items.length > 0 && (
        <ul className="space-y-2" aria-label="Files to add">
          {items.map((i) => (
            <li key={i.id} className="rounded-inner bg-inner p-3">
              <div className="flex items-center gap-3">
                <FileText className="size-4 shrink-0 text-muted" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-sm text-ink">{i.file.name}</span>
                <span className="shrink-0 text-xs text-muted">{formatBytes(i.file.size)}</span>
                {i.state === 'sending' && <Loader2 className="size-4 animate-spin text-accent" aria-label="Uploading" />}
                {i.state === 'done' && <CheckCircle2 className="size-4 text-positive" aria-label="Added" />}
                {(i.state === 'error' || i.refused) && <AlertTriangle className="size-4 text-negative" aria-label="Problem" />}
                {i.state === 'ready' && (
                  <button type="button" aria-label={`Remove ${i.file.name}`} onClick={() => setItems((l) => l.filter((x) => x.id !== i.id))} className="text-muted hover:text-ink">
                    <X className="size-4" aria-hidden />
                  </button>
                )}
              </div>
              {i.state === 'sending' && (
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line" role="progressbar" aria-valuenow={Math.round(i.progress * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={`Uploading ${i.file.name}`}>
                  <div className="h-full rounded-full bg-accent-gradient transition-[width]" style={{ width: `${Math.round(i.progress * 100)}%` }} />
                </div>
              )}
              {(i.refused || i.error) && (
                <p role="alert" className="mt-1.5 text-xs text-negative">
                  {i.refused ?? i.error}
                </p>
              )}
              {i.results && <ul className="mt-2 space-y-1.5">{i.results.map((r) => <ResultNote key={r.id} r={r} />)}</ul>}
            </li>
          ))}
        </ul>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <SegmentSelect segments={segments} value={segmentId} onChange={setSegmentId} />
        <TypeSelect value={chosenType} onChange={setChosenType} />
      </div>
      {hasTable && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Text column" hint="Spreadsheets only. Leave blank to use the column with the longest answers.">
            <input className={inputClass} value={textColumn} onChange={(e) => setTextColumn(e.target.value)} placeholder="Feedback" />
          </Field>
          <Field label="Segment column" hint="Optional: a column naming each row's segment.">
            <input className={inputClass} value={segmentColumn} onChange={(e) => setSegmentColumn(e.target.value)} placeholder="Plan" />
          </Field>
        </div>
      )}
      <div className="flex justify-end">
        <Button type="button" loading={busy} disabled={sendable.length === 0} onClick={send}>
          {sendable.length > 1 ? `Add ${sendable.length} files` : 'Add file'}
        </Button>
      </div>
    </div>
  )
}

function PasteTab({ campaignId, segments }: { campaignId: string; segments: Segment[] }) {
  const refresh = useRefreshVault()
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [segmentId, setSegmentId] = useState('')
  const [chosenType, setChosenType] = useState<ChosenType>('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [added, setAdded] = useState<Ingested[] | null>(null)

  async function add() {
    setBusy(true)
    setError(null)
    try {
      const out = await uploadSource(noteFile(text, title), { campaignId, segmentId: segmentId || null, sourceType: chosenType || null })
      setAdded(out.resources)
      setText('')
      setTitle('')
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The note could not be added.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Field label="Title">
        <input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Call with Acme, 12 Oct" />
      </Field>
      <Field label="Text" hint="An interview transcript, a support ticket, survey answers: anything customers said.">
        <textarea className={cn(inputClass, 'h-44 resize-y rounded-inner py-3')} value={text} onChange={(e) => setText(e.target.value)} />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <SegmentSelect segments={segments} value={segmentId} onChange={setSegmentId} />
        <TypeSelect value={chosenType} onChange={setChosenType} />
      </div>
      {error && <p role="alert" className="text-sm text-negative">{error}</p>}
      {added && <ul className="space-y-1.5">{added.map((r) => <ResultNote key={r.id} r={r} />)}</ul>}
      <div className="flex justify-end">
        <Button type="button" loading={busy} disabled={text.trim().length < 20} onClick={add}>
          Add note
        </Button>
      </div>
    </div>
  )
}

function WebTab({ campaignId, segments }: { campaignId: string; segments: Segment[] }) {
  const research = useResearch(campaignId)
  const [query, setQuery] = useState('')
  const [segmentId, setSegmentId] = useState('')
  const results = research.data

  return (
    <div className="space-y-4">
      <Field label="What should we look for?" hint="Public pages that mention your topic, for example reviews or forum threads. You approve what is kept.">
        <input className={inputClass} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="invoice software month-end reconciliation complaints" />
      </Field>
      <SegmentSelect segments={segments} value={segmentId} onChange={setSegmentId} />
      {research.isError && <p role="alert" className="text-sm text-negative">{research.error.message}</p>}
      {results && (
        <ul className="space-y-2" aria-label="Search results">
          {results.length === 0 && <li className="text-sm text-muted">Nothing readable was found. Try different words.</li>}
          {results.map((r) => (
            <li key={r.url} className="rounded-inner bg-inner p-3 text-sm">
              <span className="block truncate font-medium text-ink">{r.title}</span>
              <span className="block truncate text-xs text-muted">{r.url}</span>
              {r.resource ? (
                <span className="mt-1 block text-xs text-positive">Added for review{r.resource.duplicate ? ' (already in this campaign)' : ''}</span>
              ) : (
                <span className="mt-1 block text-xs text-muted">Skipped: {r.skipped ?? 'not readable'}</span>
              )}
            </li>
          ))}
        </ul>
      )}
      <div className="flex justify-end">
        <Button type="button" loading={research.isPending} disabled={query.trim().length < 3} onClick={() => research.mutate({ query: query.trim(), segmentId: segmentId || null })}>
          Search the web
        </Button>
      </div>
    </div>
  )
}

/** A button that opens the "add sources" dialog: upload files, paste text or search the web. */
export function AddSources({ campaignId, segments }: { campaignId: string; segments: Segment[] }) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<Tab>('upload')
  const titleId = useId()
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button>
          <Plus className="size-4" aria-hidden /> Add sources
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content aria-labelledby={titleId} className="fixed top-1/2 left-1/2 z-50 max-h-[90dvh] w-[calc(100vw-2rem)] max-w-xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-card border border-line bg-card p-6 shadow-lift outline-none">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <Dialog.Title id={titleId} className="text-lg font-semibold text-ink">Add sources</Dialog.Title>
              <Dialog.Description className="text-xs text-muted">Personal details are hidden before anything is stored. You review each source before it is used.</Dialog.Description>
            </div>
            <Dialog.Close aria-label="Close" className="grid size-9 shrink-0 place-items-center rounded-full text-muted hover:bg-inner hover:text-ink">
              <X className="size-4" aria-hidden />
            </Dialog.Close>
          </div>
          <SegmentedControl<Tab>
            label="How to add"
            className="mb-5 w-full [&>button]:flex-1"
            value={tab}
            onChange={setTab}
            options={[{ value: 'upload', label: 'Files' }, { value: 'paste', label: 'Paste text' }, { value: 'web', label: 'Web research' }]}
          />
          {/* All three stay mounted so switching tabs never loses an upload in progress. */}
          <div hidden={tab !== 'upload'}><UploadTab campaignId={campaignId} segments={segments} /></div>
          <div hidden={tab !== 'paste'}><PasteTab campaignId={campaignId} segments={segments} /></div>
          <div hidden={tab !== 'web'}><WebTab campaignId={campaignId} segments={segments} /></div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
