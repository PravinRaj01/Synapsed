import { Sparkles } from 'lucide-react'
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

export function LaboratoryStub() {
  return (
    <>
      <PageHeader title="Discovery Laboratory" subtitle="Watch the analysis pipeline run, and test what-if scenarios." />
      <Soon icon={<Sparkles className="size-6" />} title="Coming soon">The live pipeline canvas and the scenario forecast.</Soon>
    </>
  )
}
