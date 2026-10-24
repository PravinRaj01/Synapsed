import { BookOpenCheck, FileText, Lightbulb, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'
import { PageHeader } from '@/components/layout/PageHeader'
import { Card } from '@/components/ui/Card'

function Soon({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <Card className="grid place-items-center gap-3 py-16 text-center">
      <span className="grid size-12 place-items-center rounded-full bg-accent-tint text-accent">{icon}</span>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="max-w-md text-sm text-muted">{children}</p>
    </Card>
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
