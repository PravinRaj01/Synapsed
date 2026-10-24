import { Lightbulb } from 'lucide-react'
import { lazy, Suspense, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { ExportBar } from '@/components/report/ExportBar'
import { SegmentHeatmap } from '@/components/report/SegmentHeatmap'
import { ThemesTable } from '@/components/report/ThemesTable'
import { SourceViewer } from '@/components/vault/SourceViewer'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useCampaigns } from '@/lib/campaigns'
import { SORT_LABEL, sortThemes, type SortKey } from '@/lib/report'
import { useSegments, useThemes } from '@/lib/vault'
import { useCampaign } from '@/stores/campaign'

// The chart library is large, so the Insights Studio is only fetched when its tab is opened.
const InsightsStudio = lazy(() => import('@/components/insights/InsightsStudio'))

type Tab = 'report' | 'insights'
const TABS: { value: Tab; label: string }[] = [{ value: 'report', label: 'Problem space' }, { value: 'insights', label: 'Insights Studio' }]

export default function Roadmap() {
  const [params, setParams] = useSearchParams()
  const tab: Tab = params.get('tab') === 'insights' ? 'insights' : 'report' // the tab is in the address, so it survives a reload and can be shared
  const setTab = (next: Tab) => setParams(next === 'report' ? {} : { tab: next }, { replace: true })
  const campaigns = useCampaigns()
  const { campaignId } = useCampaign()
  const campaign = campaigns.data?.find((c) => c.id === campaignId) ?? campaigns.data?.[0]
  const themes = useThemes(campaign?.id)
  const segments = useSegments(campaign?.id)
  const [sort, setSort] = useState<SortKey>('impact')
  const [openSource, setOpenSource] = useState<string | null>(null)
  const [today] = useState(() => new Date()) // for the printed heading
  const sorted = useMemo(() => sortThemes(themes.data ?? [], sort), [themes.data, sort])

  const header = (
    <PageHeader
      title="Roadmap"
      subtitle="The problem space report, insights studio and a Now / Next / Later board."
      actions={campaign && sorted.length > 0 && tab === 'report' ? <ExportBar campaign={campaign.name} themes={sorted} /> : undefined}
    />
  )

  if (campaigns.isLoading || (campaign && themes.isLoading)) {
    return <>{header}<div role="status" aria-label="Loading the report" className="h-80 animate-pulse rounded-card bg-card shadow-card" /></>
  }
  const failed = campaigns.isError ? campaigns : themes.isError ? themes : null
  if (failed) {
    return (
      <>
        {header}
        <Card className="py-14 text-center">
          <p role="alert" className="text-sm text-negative">{failed.error?.message}</p>
          <Button className="mt-4" onClick={() => failed.refetch()}>Try again</Button>
        </Card>
      </>
    )
  }
  if (!campaign || sorted.length === 0) {
    return (
      <>
        {header}
        <Card className="grid place-items-center gap-3 py-16 text-center">
          <span className="grid size-12 place-items-center rounded-full bg-accent-tint text-accent"><Lightbulb className="size-6" aria-hidden /></span>
          <h2 className="text-lg font-semibold text-ink">No themes yet</h2>
          <p className="max-w-md text-sm text-muted">The report is built from analysed sources. Add and approve sources in the Knowledge Vault, then run the analysis.</p>
          <Link to="/vault" className="text-sm font-medium text-accent hover:underline">Open the Knowledge Vault</Link>
        </Card>
      </>
    )
  }

  const report = (
    <>
      <div className="mb-6 hidden print:block">
        <h2 className="text-xl font-semibold">Problem space report: {campaign.name}</h2>
        <p className="text-sm text-muted">{today.toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })}. Business impact is customer weight × severity, scaled so the strongest theme is 100.</p>
      </div>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
          <p className="text-sm text-muted">{sorted.length} {sorted.length === 1 ? 'theme' : 'themes'}, ranked by</p>
          <SegmentedControl<SortKey>
            label="Rank themes by"
            value={sort}
            onChange={setSort}
            options={(Object.keys(SORT_LABEL) as SortKey[]).map((k) => ({ value: k, label: SORT_LABEL[k] }))}
          />
        </div>
        <ThemesTable themes={sorted} onOpenSource={setOpenSource} />
        <SegmentHeatmap themes={sorted} />
      </div>
    </>
  )

  return (
    <>
      {header}
      <SegmentedControl<Tab> label="Roadmap view" value={tab} onChange={setTab} options={TABS} className="mb-4 print:hidden" />
      {tab === 'insights' ? (
        <Suspense fallback={<div role="status" aria-label="Loading the studio" className="h-96 animate-pulse rounded-card bg-card shadow-card" />}>
          <InsightsStudio campaignId={campaign.id} />
        </Suspense>
      ) : (
        report
      )}
      <SourceViewer id={openSource} segments={segments.data ?? []} onClose={() => setOpenSource(null)} />
    </>
  )
}
