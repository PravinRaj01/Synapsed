import { DndContext, DragOverlay, MouseSensor, TouchSensor, useDraggable, useDroppable, useSensor, useSensors, type DragEndEvent, type DragStartEvent } from '@dnd-kit/core'
import * as Menu from '@radix-ui/react-dropdown-menu'
import { ArrowRightLeft, GripVertical } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Chip } from '@/components/ui/Chip'
import { HORIZONS, groupByHorizon, horizonLabel, type Horizon, type RoadmapItem } from '@/lib/board'
import { cn } from '@/lib/cn'

type Handlers = { onMove: (id: string, horizon: Horizon) => void; onOpen: (item: RoadmapItem) => void }

function Scores({ item }: { item: RoadmapItem }) {
  return (
    <span className="flex items-center gap-1.5 text-[11px] text-muted tabular-nums" title={`Impact ${item.impact_score}, confidence ${item.confidence_score}, ease ${item.ease_score}`}>
      <span>I {item.impact_score}</span>
      <span aria-hidden>·</span>
      <span>C {item.confidence_score}</span>
      <span aria-hidden>·</span>
      <span>E {item.ease_score}</span>
    </span>
  )
}

/** The card as it looks while it is lifted: no menu, a little tilt. */
function CardBody({ item, lifted }: { item: RoadmapItem; lifted?: boolean }) {
  return (
    <div className={cn('rounded-inner border border-line bg-card p-4 shadow-card', lifted && 'rotate-1 shadow-lift')}>
      <p className="flex items-center gap-2 text-xs text-muted">
        <span className="size-2 shrink-0 rounded-full" style={{ background: item.color ?? 'var(--accent)' }} aria-hidden />
        <span className="truncate">{item.theme ?? 'No theme'}</span>
      </p>
      <p className="mt-1.5 text-sm font-medium text-ink">{item.title}</p>
      <div className="mt-3 flex items-center justify-between gap-2">
        <Chip tone="accent" title="Impact × confidence × ease">ICE {item.ice_score}</Chip>
        <Scores item={item} />
      </div>
    </div>
  )
}

function BoardCard({ item, draggable, onMove, onOpen }: Handlers & { item: RoadmapItem; draggable: boolean }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: item.id, disabled: !draggable })
  return (
    <li ref={setNodeRef} className={cn('group relative', isDragging && 'opacity-40')}>
      {/* The card can be dragged by a pointer; for the keyboard and screen readers the Move to menu is the way, so the wrapper is not a second tab stop or a button around a button. */}
      <div {...(draggable ? { ...attributes, ...listeners, role: undefined, tabIndex: -1 } : {})} className={cn(draggable && 'cursor-grab touch-manipulation active:cursor-grabbing')}>
        <button type="button" onClick={() => onOpen(item)} aria-label={`Open ${item.title}`} className="block w-full rounded-inner text-left">
          <CardBody item={item} />
        </button>
      </div>
      <Menu.Root>
        <Menu.Trigger
          aria-label={`Move ${item.title}`}
          className="absolute top-2 right-2 grid size-7 place-items-center rounded-full text-muted opacity-100 transition-colors hover:bg-inner hover:text-ink sm:opacity-0 sm:group-focus-within:opacity-100 sm:group-hover:opacity-100"
        >
          {draggable ? <GripVertical className="size-4" aria-hidden /> : <ArrowRightLeft className="size-4" aria-hidden />}
        </Menu.Trigger>
        <Menu.Portal>
          <Menu.Content align="end" sideOffset={6} className="z-50 min-w-40 rounded-card border border-line bg-card p-2 shadow-lift">
            <Menu.Label className="px-3 py-1.5 text-xs font-medium text-muted">Move to</Menu.Label>
            {HORIZONS.filter((h) => h.key !== item.horizon).map((h) => (
              <Menu.Item key={h.key} onSelect={() => onMove(item.id, h.key)} className="cursor-pointer rounded-inner px-3 py-2 text-sm text-ink outline-none data-[highlighted]:bg-inner">
                {h.label}
              </Menu.Item>
            ))}
          </Menu.Content>
        </Menu.Portal>
      </Menu.Root>
    </li>
  )
}

function Column({ horizon, items, draggable, onMove, onOpen }: Handlers & { horizon: (typeof HORIZONS)[number]; items: RoadmapItem[]; draggable: boolean }) {
  const { setNodeRef, isOver } = useDroppable({ id: horizon.key })
  return (
    <section aria-label={`${horizon.label}: ${items.length} ${items.length === 1 ? 'item' : 'items'}`} className={cn('flex min-h-48 flex-col rounded-card border border-line bg-inner p-3 transition-colors', isOver && 'border-accent bg-accent-tint')}>
      <header className="mb-3 flex items-baseline justify-between gap-2 px-1">
        <h3 className="text-sm font-semibold text-ink">{horizon.label}</h3>
        <span className="text-xs text-muted">{items.length}</span>
      </header>
      <p className="mb-3 px-1 text-xs text-muted">{horizon.hint}</p>
      <ul ref={setNodeRef} className="flex-1 space-y-3">
        {items.map((item) => (
          <BoardCard key={item.id} item={item} draggable={draggable} onMove={onMove} onOpen={onOpen} />
        ))}
        {items.length === 0 && <li className="rounded-inner border border-dashed border-line px-3 py-8 text-center text-xs text-muted">{draggable ? 'Drop a card here' : 'Nothing here yet'}</li>}
      </ul>
    </section>
  )
}

/**
 * The Now / Next / Later board. Drag a card to another column with a mouse or a finger (press and hold), or use the
 * card's Move to menu, which is the way for the keyboard and screen readers, and on a phone where dragging would fight scrolling.
 */
export function Board({ items, draggable, onMove, onOpen }: Handlers & { items: RoadmapItem[]; draggable: boolean }) {
  const groups = useMemo(() => groupByHorizon(items), [items])
  const [lifted, setLifted] = useState<RoadmapItem | null>(null)
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 6 } }), // a click opens the card; a drag of a few pixels lifts it
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 6 } }), // press and hold, so scrolling still works
  )

  const start = (e: DragStartEvent) => setLifted(items.find((i) => i.id === e.active.id) ?? null)
  const end = (e: DragEndEvent) => {
    setLifted(null)
    const target = e.over?.id
    const item = items.find((i) => i.id === e.active.id)
    if (item && (target === 'now' || target === 'next' || target === 'later') && target !== item.horizon) onMove(item.id, target)
  }

  return (
    <DndContext sensors={sensors} onDragStart={start} onDragEnd={end} onDragCancel={() => setLifted(null)}>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {HORIZONS.map((h) => (
          <Column key={h.key} horizon={h} items={groups[h.key]} draggable={draggable} onMove={onMove} onOpen={onOpen} />
        ))}
      </div>
      <DragOverlay dropAnimation={null}>{lifted ? <CardBody item={lifted} lifted /> : null}</DragOverlay>
      <p className="sr-only" aria-live="polite">{lifted ? `Moving ${lifted.title} from ${horizonLabel(lifted.horizon)}` : ''}</p>
    </DndContext>
  )
}
