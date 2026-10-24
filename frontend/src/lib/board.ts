import type { components } from '@/api/schema'

export type RoadmapItem = components['schemas']['RoadmapItemOut']
export type Horizon = RoadmapItem['horizon']
export type Prd = components['schemas']['PrdOut']
export type PrdVersion = components['schemas']['PrdVersionOut']
export type Evidence = components['schemas']['EvidenceOut']
export type UserStory = components['schemas']['UserStoryOut']

export const HORIZONS: { key: Horizon; label: string; hint: string }[] = [
  { key: 'now', label: 'Now', hint: 'The best bets for this cycle' },
  { key: 'next', label: 'Next', hint: 'Once the first ones are done' },
  { key: 'later', label: 'Later', hint: 'Worth keeping an eye on' },
]

export const horizonLabel = (h: Horizon): string => HORIZONS.find((x) => x.key === h)?.label ?? h

/** ICE: impact × confidence × ease, each 1 to 10, so 1 to 1000. The server computes the stored one; this previews an edit. */
export const iceScore = (impact: number, confidence: number, ease: number): number => impact * confidence * ease

const byIce = (a: RoadmapItem, b: RoadmapItem) => b.ice_score - a.ice_score || a.title.localeCompare(b.title)

/** The board's columns, each highest ICE first, so a card's place in its column is never a surprise. */
export function groupByHorizon(items: RoadmapItem[]): Record<Horizon, RoadmapItem[]> {
  const out: Record<Horizon, RoadmapItem[]> = { now: [], next: [], later: [] }
  for (const item of [...items].sort(byIce)) out[item.horizon].push(item)
  return out
}

/** The list with one card moved to another column; every other card keeps its object. Moving to where it already is changes nothing. */
export function withHorizon(items: RoadmapItem[], id: string, horizon: Horizon): RoadmapItem[] {
  return items.map((i) => (i.id === id && i.horizon !== horizon ? { ...i, horizon } : i))
}

export type ItemEdit = { title: string; description: string; impact_score: number; confidence_score: number; ease_score: number }

export const editOf = (i: RoadmapItem): ItemEdit => ({ title: i.title, description: i.description, impact_score: i.impact_score, confidence_score: i.confidence_score, ease_score: i.ease_score })

/** Only what changed, tidied, for a PATCH; null when nothing changed or the edit is not valid (an empty title or description). */
export function patchFor(item: RoadmapItem, edit: ItemEdit): Partial<ItemEdit> | null {
  const title = edit.title.split(/\s+/).filter(Boolean).join(' ')
  const description = edit.description.trim()
  if (!title || !description) return null
  const patch: Partial<ItemEdit> = {}
  if (title !== item.title) patch.title = title
  if (description !== item.description) patch.description = description
  for (const key of ['impact_score', 'confidence_score', 'ease_score'] as const) {
    const value = Math.min(10, Math.max(1, Math.round(edit[key])))
    if (value !== item[key]) patch[key] = value
  }
  return Object.keys(patch).length > 0 ? patch : null
}

// ---------------------------------------------------------------- PRDs

/** "Make bank matching reliable" -> "make-bank-matching-reliable-prd.md". */
export function prdFilename(title: string): string {
  const slug = title.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60)
  return `${slug || 'prd'}-prd.md`
}

/** The evidence the PRD cites, by its number, so [3] in a user story can be shown with its quote. */
export function evidenceByNumber(prd: Prd): Map<number, Evidence> {
  return new Map(prd.content.evidence.map((e) => [e.n, e]))
}

/** The quotes behind one user story. A number the evidence does not have is skipped rather than shown as a broken link. */
export function storyEvidence(story: UserStory, evidence: Map<number, Evidence>): Evidence[] {
  return story.evidence.flatMap((n) => {
    const found = evidence.get(n)
    return found ? [found] : []
  })
}

/** Newest first, as the server returns them; a title missing from an old version falls back to the item's. */
export const versionLabel = (v: PrdVersion, index: number, total: number): string => `Version ${total - index}${v.jira_issue_key ? ` · ${v.jira_issue_key}` : ''}`

/** Seconds as "12s" or "1m 05s", for the counter while a PRD is being written. */
export function elapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`
}
