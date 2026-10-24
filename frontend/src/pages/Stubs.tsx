import { BookOpenCheck, FileText, Lightbulb, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card } from '@/components/ui/Card'
import { StatsCard } from '@/components/ui/StatsCard'
import { useCampaigns } from '@/lib/campaigns'
import { firstName, useSession } from '@/lib/session'
import { useCampaign } from '@/stores/campaign'

function greeting(date = new Date()) {
  const h = date.getHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

function Soon({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <Card className="grid place-items-center gap-3 py-16 text-center">
      <span className="grid size-12 place-items-center rounded-full bg-accent-tint text-accent">{icon}</span>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="max-w-md text-sm text-muted">{children}</p>
    </Card>
  )
}

/** The dashboard shell: a greeting and the active campaign's real counts. The full dashboard arrives in the next step. */
export function DashboardStub() {
  const { data: user } = useSession()
  const { data: campaigns = [] } = useCampaigns()
  const { campaignId } = useCampaign()
  const campaign = campaigns.find((c) => c.id === campaignId)
  return (
    <>
      <PageHeader title={`${greeting()}, ${user ? firstName(user) : 'there'}`} subtitle="Stay on top of your research, monitor progress and track what customers are saying." />
      {campaign ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatsCard hero title="Insights found" value={campaign.insights} icon={Lightbulb} hint={campaign.name} />
          <StatsCard title="Sources indexed" value={campaign.resources} icon={BookOpenCheck} />
          <StatsCard title="Awaiting approval" value={campaign.staged} icon={FileText} />
          <StatsCard title="Themes" value={campaign.themes} icon={Sparkles} />
        </div>
      ) : (
        <Soon icon={<Sparkles className="size-6" />} title="Let's set up your first campaign">Campaign setup, with a ready-made demo workspace, arrives in the next step.</Soon>
      )}
    </>
  )
}

export function VaultStub() {
  return (
    <>
      <PageHeader title="Knowledge Vault" subtitle="Upload, review and approve the sources your analysis is built on." />
      <Soon icon={<BookOpenCheck className="size-6" />} title="Coming soon">Uploads, the staging preview and the pain points explorer land here.</Soon>
    </>
  )
}

export function ChatStub() {
  return (
    <>
      <PageHeader title="Deep Workspace" subtitle="Ask questions of your sources and get answers with verified quotes." />
      <Soon icon={<FileText className="size-6" />} title="Coming soon">A document viewer with highlights and a chat that cites its evidence.</Soon>
    </>
  )
}

export function RoadmapStub() {
  return (
    <>
      <PageHeader title="Roadmap" subtitle="The problem space report, insights studio and a Now / Next / Later board." />
      <Soon icon={<Lightbulb className="size-6" />} title="Coming soon">Themes by business impact, charts, PRDs and the roadmap board.</Soon>
    </>
  )
}

export function LaboratoryStub() {
  return (
    <>
      <PageHeader title="Discovery Laboratory" subtitle="Watch the analysis pipeline run, and test what-if scenarios." />
      <Soon icon={<Sparkles className="size-6" />} title="Coming soon">The live pipeline canvas and the scenario forecast.</Soon>
    </>
  )
}

export function OnboardingStub() {
  return (
    <>
      <PageHeader title="New campaign" subtitle="Tell us about your product and your customer segments." />
      <Soon icon={<Sparkles className="size-6" />} title="Coming in the next step">The setup wizard, with segment weights and a demo sandbox, is built next.</Soon>
    </>
  )
}
