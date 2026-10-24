import { MessageSquareText } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { ChatPane } from '@/components/chat/ChatPane'
import { DocumentPane, type OpenDoc } from '@/components/chat/DocumentPane'
import { SourcesChecklist } from '@/components/chat/SourcesChecklist'
import { PageHeader } from '@/components/layout/PageHeader'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useCampaigns } from '@/lib/campaigns'
import { useDeepChat, type Focus } from '@/lib/chat'
import { useExtraWide } from '@/lib/useWide'
import { useSources } from '@/lib/vault'
import { useCampaign } from '@/stores/campaign'

type Pane = 'chat' | 'doc' | 'sources'

export default function Chat() {
  const campaigns = useCampaigns()
  const { campaignId } = useCampaign()
  const campaign = campaigns.data?.find((c) => c.id === campaignId) ?? campaigns.data?.[0]
  const sources = useSources(campaign?.id)
  const wide = useExtraWide()

  const approved = useMemo(() => (sources.data ?? []).filter((s) => s.status === 'approved'), [sources.data])
  const [excluded, setExcluded] = useState<Set<string>>(new Set())
  const [doc, setDoc] = useState<OpenDoc | null>(null)
  const [pane, setPane] = useState<Pane>('chat')

  const ticked = approved.filter((s) => !excluded.has(s.id))
  const sourceIds = excluded.size === 0 ? null : ticked.map((s) => s.id) // null: every approved source, including ones approved later
  const chat = useDeepChat(campaign?.id, sourceIds)
  const blocked = approved.length > 0 && ticked.length === 0 ? 'Tick at least one source to ask a question.' : null

  const open = (id: string, focus: Focus | null = null) => {
    setDoc((d) => ({ id, focus, key: (d?.key ?? 0) + 1 }))
    setPane('doc')
  }
  const toggle = (id: string) =>
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const header = <PageHeader title="Deep Workspace" subtitle="Ask questions of your sources and get answers with verified quotes." />

  if (campaigns.isLoading || (campaign && sources.isLoading)) {
    return <>{header}<div role="status" aria-label="Loading" className="h-96 animate-pulse rounded-card bg-card shadow-card" /></>
  }
  const failed = campaigns.isError ? campaigns : sources.isError ? sources : null
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
  if (!campaign || approved.length === 0) {
    return (
      <>
        {header}
        <Card className="grid place-items-center gap-3 py-16 text-center">
          <span className="grid size-12 place-items-center rounded-full bg-accent-tint text-accent"><MessageSquareText className="size-6" aria-hidden /></span>
          <h2 className="text-lg font-semibold text-ink">Nothing to ask yet</h2>
          <p className="max-w-md text-sm text-muted">Chat answers only from sources you have approved. Add and approve some in the Knowledge Vault, or load the demo from the dashboard.</p>
          <Link to="/vault" className="text-sm font-medium text-accent hover:underline">Open the Knowledge Vault</Link>
        </Card>
      </>
    )
  }

  const scope = excluded.size === 0 ? `All ${approved.length} approved ${approved.length === 1 ? 'source' : 'sources'}` : `${ticked.length} of ${approved.length} sources`
  const sourcesPane = (
    <SourcesChecklist sources={approved} excluded={excluded} openId={doc?.id ?? null} onToggle={toggle} onAll={() => setExcluded(new Set())} onNone={() => setExcluded(new Set(approved.map((s) => s.id)))} onOpen={(id) => open(id)} />
  )
  const chatPane = <ChatPane messages={chat.messages} pending={chat.pending} blocked={blocked} scope={scope} onAsk={chat.ask} onClear={chat.clear} onOpen={open} />
  const docPane = <DocumentPane doc={doc} />

  return (
    <>
      {header}
      {wide ? (
        <Card className="grid h-[calc(100dvh-12rem)] min-h-[34rem] grid-cols-[16rem_minmax(0,1fr)_minmax(0,1fr)] divide-x divide-line overflow-hidden p-0">
          <div className="min-h-0">{sourcesPane}</div>
          <div className="min-h-0">{chatPane}</div>
          <div className="min-h-0">{docPane}</div>
        </Card>
      ) : (
        <div className="space-y-3">
          <SegmentedControl<Pane> label="Workspace view" value={pane} onChange={setPane} options={[{ value: 'chat', label: 'Chat' }, { value: 'doc', label: 'Document' }, { value: 'sources', label: `Sources (${ticked.length})` }]} />
          <Card className="h-[calc(100dvh-16rem)] min-h-[28rem] overflow-hidden p-0">{pane === 'chat' ? chatPane : pane === 'doc' ? docPane : sourcesPane}</Card>
        </div>
      )}
    </>
  )
}
