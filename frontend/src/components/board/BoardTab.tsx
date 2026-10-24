import { Map as MapIcon } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { BoardSkeleton, FadeIn, Loading } from '@/components/ui/Skeleton'
import { horizonLabel, type Horizon } from '@/lib/board'
import { useMoveItem, useRoadmap } from '@/lib/roadmap'
import { useWide } from '@/lib/useWide'
import { Board } from './Board'
import { ItemDrawer } from './ItemDrawer'

/** The third tab of the Roadmap page: the Now / Next / Later board, and a card's panel with its PRDs. */
export default function BoardTab({ campaignId }: { campaignId: string }) {
  const roadmap = useRoadmap(campaignId)
  const move = useMoveItem(campaignId)
  const wide = useWide()
  const [openId, setOpenId] = useState<string | null>(null)
  const items = roadmap.data ?? []
  const open = items.find((i) => i.id === openId) ?? null // the live card, so a saved edit shows in its own panel

  async function onMove(id: string, horizon: Horizon) {
    const item = items.find((i) => i.id === id)
    try {
      await move.mutateAsync({ id, horizon })
      toast.success(`Moved to ${horizonLabel(horizon)}.`)
    } catch (e) {
      toast.error(`${item ? `"${item.title}" stayed in ${horizonLabel(item.horizon)}. ` : ''}${e instanceof Error ? e.message : 'The move was not saved.'}`)
    }
  }

  if (roadmap.isLoading) return <Loading label="Loading the board"><BoardSkeleton /></Loading>
  if (roadmap.isError) {
    return (
      <Card className="py-12 text-center">
        <p role="alert" className="text-sm text-negative">{roadmap.error.message}</p>
        <Button className="mt-3" size="sm" onClick={() => roadmap.refetch()}>Try again</Button>
      </Card>
    )
  }
  if (items.length === 0) {
    return (
      <Card className="grid place-items-center gap-3 py-16 text-center">
        <span className="grid size-12 place-items-center rounded-full bg-accent-tint text-accent"><MapIcon className="size-6" aria-hidden /></span>
        <h2 className="text-lg font-semibold text-ink">No roadmap items yet</h2>
        <p className="max-w-md text-sm text-muted">The analysis proposes one item for each problem theme. Approve sources and run it in the Knowledge Vault.</p>
        <Link to="/vault" className="text-sm font-medium text-accent hover:underline">Open the Knowledge Vault</Link>
      </Card>
    )
  }
  return (
    <FadeIn>
      <p className="mb-4 text-sm text-muted">
        {items.length} {items.length === 1 ? 'item' : 'items'}, highest ICE first in each column.{' '}
        {wide ? 'Drag a card to another column, or open it to edit it and write its PRD.' : 'Open a card to edit it and write its PRD; use its menu to move it.'}
      </p>
      <Board items={items} draggable={wide} onMove={onMove} onOpen={(i) => setOpenId(i.id)} />
      <ItemDrawer item={open} campaignId={campaignId} onClose={() => setOpenId(null)} />
    </FadeIn>
  )
}
