import { Download, FileText, Printer } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { downloadText } from '@/lib/download'
import { fileSlug, reportCsv, reportMarkdown } from '@/lib/report'
import type { ThemeRow } from '@/lib/vault'

/** Save the report as a spreadsheet or a Markdown document, or print it (the browser's print dialog can save a PDF). */
export function ExportBar({ campaign, themes }: { campaign: string; themes: ThemeRow[] }) {
  const slug = fileSlug(campaign)
  return (
    <div className="flex flex-wrap items-center gap-2 print:hidden">
      <Button variant="secondary" size="sm" disabled={themes.length === 0} onClick={() => downloadText(`${slug}-themes.csv`, reportCsv(themes), 'text/csv')}>
        <Download className="size-3.5" aria-hidden /> CSV
      </Button>
      <Button variant="secondary" size="sm" disabled={themes.length === 0} onClick={() => downloadText(`${slug}-problem-space.md`, reportMarkdown(campaign, themes), 'text/markdown')}>
        <FileText className="size-3.5" aria-hidden /> Markdown
      </Button>
      <Button variant="secondary" size="sm" disabled={themes.length === 0} onClick={() => window.print()}>
        <Printer className="size-3.5" aria-hidden /> Print or PDF
      </Button>
    </div>
  )
}
