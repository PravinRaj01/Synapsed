import { useMutation } from '@tanstack/react-query'
import { create } from 'zustand'
import type { components } from '@/api/schema'
import { api, unwrap } from './api'
import { historyFor, type Turn } from './chatHistory'
import type { Highlight } from './vaultLogic'

export type Citation = components['schemas']['CitationOut']

export type ChatMessage =
  | { id: string; role: 'user'; content: string }
  | { id: string; role: 'assistant'; content: string; citations: Citation[]; refused: boolean; model: string | null; tokens: number; passages: number }
  | { id: string; role: 'error'; content: string }

// ---------------------------------------------------------------- reading an answer

export type AnswerPart = { type: 'text'; text: string } | { type: 'ref'; n: number }

/** Split an answer into plain text and [n] footnote markers, so the markers can be made clickable. */
export function splitFootnotes(answer: string): AnswerPart[] {
  const parts: AnswerPart[] = []
  let last = 0
  for (const m of answer.matchAll(/\[(\d{1,3})\]/g)) {
    if (m.index > last) parts.push({ type: 'text', text: answer.slice(last, m.index) })
    parts.push({ type: 'ref', n: Number(m[1]) })
    last = m.index + m[0].length
  }
  if (last < answer.length) parts.push({ type: 'text', text: answer.slice(last) })
  return parts
}

export type Focus = { start: number; end: number }

/**
 * The highlights to draw when one quote is in focus: the theme highlights that overlap the quote make way for it, and
 * the quote itself is added so it can be flashed. The rest stay as they were.
 */
export function withFocus(highlights: Highlight[], focus: Focus | null): Highlight[] {
  if (!focus) return highlights
  const apart = highlights.filter((h) => h.end_offset <= focus.start || h.start_offset >= focus.end)
  return [...apart, { start_offset: focus.start, end_offset: focus.end, focus: true }]
}

/** The conversation's turns the API should see, as the page keeps them. */
export const turnsFor = (messages: ChatMessage[]): Turn[] => historyFor(messages)

// ---------------------------------------------------------------- one conversation per campaign

type Store = {
  byCampaign: Record<string, ChatMessage[]>
  add: (campaignId: string, message: ChatMessage) => void
  clear: (campaignId: string) => void
}

const EMPTY: ChatMessage[] = []

/** Kept in memory, so the conversation survives moving between pages but not a reload. */
export const useChatStore = create<Store>((set) => ({
  byCampaign: {},
  add: (campaignId, message) => set((s) => ({ byCampaign: { ...s.byCampaign, [campaignId]: [...(s.byCampaign[campaignId] ?? EMPTY), message] } })),
  clear: (campaignId) => set((s) => ({ byCampaign: { ...s.byCampaign, [campaignId]: EMPTY } })),
}))

let counter = 0
const nextId = () => `m${++counter}`

/** Ask questions about a campaign's approved sources; `sourceIds` null means all of them. */
export function useDeepChat(campaignId: string | null | undefined, sourceIds: string[] | null) {
  const messages = useChatStore((s) => (campaignId ? s.byCampaign[campaignId] : undefined)) ?? EMPTY
  const add = useChatStore((s) => s.add)
  const clear = useChatStore((s) => s.clear)
  const mutation = useMutation({
    mutationFn: (q: { text: string; history: Turn[] }) =>
      unwrap(api.POST('/api/v1/chat', { body: { campaign_id: campaignId!, question: q.text, history: q.history, source_ids: sourceIds } })),
  })

  async function ask(text: string) {
    const question = text.trim()
    if (question.length < 3 || !campaignId || mutation.isPending) return false
    const history = turnsFor(messages)
    add(campaignId, { id: nextId(), role: 'user', content: question })
    try {
      const r = await mutation.mutateAsync({ text: question, history })
      add(campaignId, {
        id: nextId(), role: 'assistant', refused: r.refused, citations: r.citations, model: r.model, tokens: r.tokens, passages: r.retrieved.length,
        content: r.refused ? (r.message ?? 'I could not find this in your approved sources.') : (r.answer ?? ''),
      })
    } catch (e) {
      add(campaignId, { id: nextId(), role: 'error', content: e instanceof Error ? e.message : 'Something went wrong. Please try again.' })
    }
    return true
  }

  return { messages, pending: mutation.isPending, ask, clear: () => campaignId && clear(campaignId) }
}
