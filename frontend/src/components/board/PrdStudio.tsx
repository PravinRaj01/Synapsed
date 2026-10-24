import { Download, ExternalLink, FileText, Printer, Send, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { DocumentSkeleton, FadeIn, Loading, RowsSkeleton } from '@/components/ui/Skeleton'
import { elapsed, prdFilename, versionLabel, type RoadmapItem } from '@/lib/board'
import { downloadText } from '@/lib/download'
import { printSection } from '@/lib/print'
import { useDeletePrd, useGeneratePrd, useIntegrations, usePrd, usePrdVersions, useSendToJira } from '@/lib/roadmap'
import { PrdDocument } from './PrdDocument'

/** Counts seconds while `running`, from zero each time it starts. */
function useElapsed(running: boolean): number {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    if (!running) return
    const started = Date.now()
    const timer = window.setInterval(() => setSeconds((Date.now() - started) / 1000), 500)
    return () => {
      window.clearInterval(timer)
      setSeconds(0)
    }
  }, [running])
  return seconds
}

/** Write a PRD for a roadmap card from the theme's evidence, read earlier versions, and send one on as a file, print or Jira issue. */
export function PrdStudio({ item }: { item: RoadmapItem }) {
  const versions = usePrdVersions(item.id)
  const generate = useGeneratePrd(item.id)
  const remove = useDeletePrd(item.id)
  const jira = useSendToJira(item.id)
  const integrations = useIntegrations()
  const [picked, setPicked] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [issueUrl, setIssueUrl] = useState<string | null>(null)
  const waited = useElapsed(generate.isPending)

  const list = versions.data ?? []
  const selectedId = picked && list.some((v) => v.id === picked) ? picked : (list[0]?.id ?? null) // newest unless one was chosen
  const prd = usePrd(selectedId)
  const noTheme = item.theme_id == null

  async function write() {
    try {
      const made = await generate.mutateAsync()
      setPicked(made.id)
      toast.success('PRD written.')
    } catch {
      /* the message is shown from generate.error below */
    }
  }

  async function sendToJira(id: string) {
    try {
      const issue = await jira.mutateAsync(id)
      setIssueUrl(issue.url)
      toast.success(`Created ${issue.jira_issue_key} in Jira.`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Jira did not accept it.')
    }
  }

  async function drop(id: string) {
    try {
      await remove.mutateAsync(id)
      setConfirmDelete(false)
      setPicked(null)
      toast.success('Version deleted.')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'The version could not be deleted.')
    }
  }

  return (
    <section aria-label="PRD" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-ink">Product requirements</h3>
          <p className="text-xs text-muted">A PRD written from what customers said about this theme, with their quotes attached.</p>
        </div>
        <Button variant="accent" size="sm" loading={generate.isPending} disabled={noTheme} onClick={write}>
          <FileText className="size-4" aria-hidden /> {list.length > 0 ? 'Write a new version' : 'Write a PRD'}
        </Button>
      </div>

      {noTheme && <p className="rounded-inner bg-warning-tint px-4 py-3 text-sm text-ink">This item has no theme, so there is no customer evidence to write a PRD from.</p>}
      {generate.isPending && (
        <p role="status" className="rounded-inner bg-accent-tint px-4 py-3 text-sm text-ink">
          Reading the evidence and writing the PRD, {elapsed(waited)} so far. This can take up to half a minute.
        </p>
      )}
      {generate.isError && <p role="alert" className="rounded-inner bg-negative-tint px-4 py-3 text-sm text-negative">{generate.error.message}</p>}

      {versions.isLoading ? (
        <Loading label="Loading PRDs"><RowsSkeleton rows={1} /></Loading>
      ) : versions.isError ? (
        <p role="alert" className="text-sm text-negative">{versions.error.message}</p>
      ) : list.length === 0 ? (
        !noTheme && !generate.isPending && <p className="text-sm text-muted">No PRD yet. Write one and it appears here.</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="prd-version">PRD version</label>
            <select id="prd-version" value={selectedId ?? ''} onChange={(e) => { setPicked(e.target.value); setConfirmDelete(false); setIssueUrl(null) }} className="h-9 rounded-full border border-line bg-inner px-3 text-sm text-ink outline-none focus:border-accent">
              {list.map((v, i) => (
                <option key={v.id} value={v.id}>
                  {versionLabel(v, i, list.length)} · {new Date(v.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })}
                </option>
              ))}
            </select>
            {prd.data && (
              <>
                <Button variant="secondary" size="sm" onClick={() => downloadText(prdFilename(prd.data.content.prd.title), prd.data.markdown, 'text/markdown')}>
                  <Download className="size-3.5" aria-hidden /> Markdown
                </Button>
                <Button variant="secondary" size="sm" onClick={() => printSection('prd')}>
                  <Printer className="size-3.5" aria-hidden /> Print or PDF
                </Button>
                {integrations.data?.jira.configured && !prd.data.jira_issue_key && (
                  <Button variant="secondary" size="sm" loading={jira.isPending} onClick={() => sendToJira(prd.data.id)}>
                    <Send className="size-3.5" aria-hidden /> Create Jira issue
                  </Button>
                )}
                {prd.data.jira_issue_key && (
                  <span className="flex items-center gap-1.5 text-xs text-muted">
                    In Jira as <strong className="text-ink">{prd.data.jira_issue_key}</strong>
                    {issueUrl && (
                      <a href={issueUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                        Open <ExternalLink className="size-3" aria-hidden />
                      </a>
                    )}
                  </span>
                )}
                {confirmDelete ? (
                  <span className="ml-auto flex items-center gap-2 text-xs">
                    <span className="text-muted">Delete this version?</span>
                    <Button size="sm" variant="secondary" loading={remove.isPending} onClick={() => drop(prd.data.id)}>Yes, delete</Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>Keep</Button>
                  </span>
                ) : (
                  <button type="button" onClick={() => setConfirmDelete(true)} aria-label="Delete this version" className="ml-auto grid size-8 place-items-center rounded-full text-muted hover:bg-inner hover:text-negative">
                    <Trash2 className="size-4" aria-hidden />
                  </button>
                )}
              </>
            )}
          </div>

          {prd.isLoading && <Loading label="Loading the PRD"><DocumentSkeleton /></Loading>}
          {prd.isError && <p role="alert" className="text-sm text-negative">{prd.error.message}</p>}
          {prd.data && (
            <FadeIn key={prd.data.id}>
              <div className="rounded-card border border-line p-5">
                <PrdDocument prd={prd.data} />
              </div>
            </FadeIn>
          )}
          {prd.data && createPortal(<div id="prd-print"><PrdDocument prd={prd.data} /></div>, document.body)}
        </>
      )}
    </section>
  )
}
