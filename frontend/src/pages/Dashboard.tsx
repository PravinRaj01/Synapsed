import { FlaskConical, Lightbulb, Map, Plus, Sparkles, Upload, BookOpenCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, Navigate, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { QuickChat } from '@/components/dashboard/QuickChat'
import { RecentActivity } from '@/components/dashboard/RecentActivity'
import { SentimentCard } from '@/components/dashboard/SentimentCard'
import { SuggestedActions } from '@/components/dashboard/SuggestedActions'
import { TopThemes } from '@/components/dashboard/TopThemes'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { StatsCard } from '@/components/ui/StatsCard'
import { useCampaigns } from '@/lib/campaigns'
import { greeting, percentChange, suggestedActions } from '@/lib/onboarding'
import { firstName, useSession } from '@/lib/session'
import { useLoadDemo, useOverview, useWorkspaces } from '@/lib/workspaces'
import { useCampaign } from '@/stores/campaign'
import { ChartCardSkeleton, FadeIn, Loading, StatCardsSkeleton } from '@/components/ui/Skeleton'

function Message({ icon, title, children, actions }: { icon: ReactNode; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <Card className="grid place-items-center gap-3 py-16 text-center">
      <span className="grid size-12 place-items-center rounded-full bg-accent-tint text-accent">{icon}</span>
      <h2 className="text-lg font-semibold">{title}</h2>
      {children && <p className="max-w-md text-sm text-muted">{children}</p>}
      {actions && <div className="mt-2 flex flex-wrap justify-center gap-2">{actions}</div>}
    </Card>
  )
}

function DashboardSkeleton() {
  return (
    <Loading label="Loading your dashboard" className="space-y-4">
      <StatCardsSkeleton />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <ChartCardSkeleton className="h-72 lg:col-span-2" />
        <ChartCardSkeleton className="h-72" />
      </div>
    </Loading>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { data: user } = useSession()
  const workspaces = useWorkspaces()
  const campaigns = useCampaigns()
  const { campaignId } = useCampaign()
  const campaign = campaigns.data?.find((c) => c.id === campaignId) ?? campaigns.data?.[0]
  const overview = useOverview(campaign?.id)
  const loadDemo = useLoadDemo()

  const header = (
    <PageHeader
      title={`${greeting()}, ${user ? firstName(user) : 'there'}`}
      subtitle="Stay on top of your research, monitor progress and track what customers are saying."
      actions={
        <Button variant="secondary" onClick={() => navigate('/onboarding')}>
          <Plus className="size-4" aria-hidden /> New campaign
        </Button>
      }
    />
  )

  // A first-time user has nothing to look at yet: set them up instead.
  if (workspaces.isSuccess && workspaces.data.length === 0) return <Navigate to="/onboarding" replace />

  const failed = workspaces.isError ? workspaces : campaigns.isError ? campaigns : overview.isError ? overview : null
  if (failed) {
    return (
      <>
        {header}
        <Message icon={<Sparkles className="size-6" />} title="We could not load your dashboard" actions={<Button onClick={() => failed.refetch()}>Try again</Button>}>
          {failed.error instanceof Error ? failed.error.message : 'Something went wrong.'}
        </Message>
      </>
    )
  }

  if (workspaces.isLoading || campaigns.isLoading || (campaign && overview.isLoading)) {
    return (
      <>
        {header}
        <DashboardSkeleton />
      </>
    )
  }

  if (!campaign || !overview.data) {
    return (
      <>
        {header}
        <Message icon={<Sparkles className="size-6" />} title="Let's set up a campaign" actions={<Button onClick={() => navigate('/onboarding')}>Create a campaign</Button>}>
          A campaign groups the interviews, tickets and surveys for one research question.
        </Message>
      </>
    )
  }

  const o = overview.data
  const empty = o.resources.total === 0

  async function demo() {
    try {
      await loadDemo.mutateAsync(campaign!.id)
      toast.success('Demo sandbox loaded.')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'The demo could not be loaded.')
    }
  }

  return (
    <>
      {header}
      {empty ? (
        <Message
          icon={<BookOpenCheck className="size-6" />}
          title="This campaign has no sources yet"
          actions={
            <>
              <Button variant="accent" loading={loadDemo.isPending} onClick={demo}>
                <FlaskConical className="size-4" aria-hidden /> Load the demo sandbox
              </Button>
              <Button variant="secondary" onClick={() => navigate('/vault')}>
                <Upload className="size-4" aria-hidden /> Upload my data
              </Button>
            </>
          }
        >
          Add interviews, tickets or surveys, or explore with ten invented sources that are already analysed.
        </Message>
      ) : (
        <FadeIn className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatsCard hero title="Insights found" value={o.insights} icon={Lightbulb} change={percentChange(o.trend.insights.current, o.trend.insights.previous)} hint={`vs previous ${o.trend.days} days`} />
            <StatsCard title="Sources indexed" value={o.resources.approved} icon={BookOpenCheck} change={percentChange(o.trend.resources.current, o.trend.resources.previous)} hint={o.resources.staged ? `${o.resources.staged} awaiting approval` : undefined} />
            <StatsCard title="Themes" value={o.themes} icon={Sparkles} change={percentChange(o.trend.themes.current, o.trend.themes.previous)} />
            <StatsCard title="Roadmap items" value={o.roadmap_items} icon={Map} hint={`${o.segments} customer ${o.segments === 1 ? 'segment' : 'segments'}`} />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <TopThemes themes={o.top_themes} />
            </div>
            <SentimentCard sentiment={o.sentiment} />
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <SuggestedActions actions={suggestedActions(o)} />
            <RecentActivity resources={o.recent_resources} />
          </div>
          {o.telemetry.calls > 0 && (
            <p className="px-1 text-xs text-muted">
              Models used so far: {o.telemetry.calls.toLocaleString()} calls, {o.telemetry.tokens.toLocaleString()} tokens
              {o.telemetry.fallbacks ? `, ${o.telemetry.fallbacks} provider switches` : ''}. <Link to="/laboratory" className="text-accent hover:underline">See the pipeline</Link>
            </p>
          )}
        </FadeIn>
      )}
      <QuickChat key={campaign.id} campaignId={campaign.id} disabled={empty} />
    </>
  )
}
