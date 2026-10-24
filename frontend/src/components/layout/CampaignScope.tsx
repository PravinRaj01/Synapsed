import * as Menu from '@radix-ui/react-dropdown-menu'
import { Check, ChevronDown, Layers } from 'lucide-react'
import { useEffect } from 'react'
import { useNavigate } from 'react-router'
import { useCampaigns } from '@/lib/campaigns'
import { useCampaign } from '@/stores/campaign'

const NONE: never[] = [] // a stable empty list: a fresh [] each render would re-run the effect below forever

/** The Global Campaign Scope: one choice here filters every page. Falls back to the first campaign if the saved one is gone. */
export function CampaignScope() {
  const { data, isLoading, isError } = useCampaigns()
  const campaigns = data ?? NONE
  const { campaignId, setCampaign } = useCampaign()
  const navigate = useNavigate()
  const active = campaigns.find((c) => c.id === campaignId)

  useEffect(() => {
    if (isLoading || isError) return // a failed load says nothing about which campaigns exist: keep the saved choice
    if (!active) setCampaign(campaigns[0]?.id ?? null)
  }, [isLoading, isError, active, campaigns, setCampaign])

  return (
    <Menu.Root>
      <Menu.Trigger className="flex h-10 max-w-[14rem] items-center gap-2 rounded-full border border-line bg-card px-4 text-sm font-medium text-ink shadow-card" aria-label="Campaign scope">
        <Layers className="size-4 shrink-0 text-accent" aria-hidden />
        <span className="truncate">{isLoading ? 'Loading…' : (active?.name ?? 'No campaign')}</span>
        <ChevronDown className="size-4 shrink-0 text-muted" aria-hidden />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="start" sideOffset={8} className="z-50 min-w-60 rounded-card border border-line bg-card p-2 shadow-lift">
          <Menu.Label className="px-3 py-1.5 text-xs font-medium text-muted">Campaign</Menu.Label>
          {campaigns.map((c) => (
            <Menu.Item key={c.id} onSelect={() => setCampaign(c.id)} className="flex cursor-pointer items-center justify-between gap-3 rounded-inner px-3 py-2 text-sm text-ink outline-none data-[highlighted]:bg-inner">
              <span className="truncate">{c.name}</span>
              {c.id === active?.id && <Check className="size-4 text-accent" aria-hidden />}
            </Menu.Item>
          ))}
          {!isLoading && campaigns.length === 0 && <p className="px-3 py-2 text-sm text-muted">Nothing here yet. Create your first campaign to begin.</p>}
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.Item onSelect={() => navigate('/onboarding')} className="cursor-pointer rounded-inner px-3 py-2 text-sm font-medium text-accent outline-none data-[highlighted]:bg-inner">
            New campaign
          </Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
