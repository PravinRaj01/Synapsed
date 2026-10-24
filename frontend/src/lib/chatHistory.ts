export const HISTORY_TURNS = 6
export type Turn = { role: 'user' | 'assistant'; content: string }

type Chatted = { role: 'user'; content: string } | { role: 'assistant'; content: string; refused: boolean } | { role: 'error'; content: string }

/** The earlier turns the API should see: real exchanges only, the most recent few, refusals and errors left out. */
export function historyFor(messages: Chatted[]): Turn[] {
  const turns: Turn[] = []
  for (const m of messages) {
    if (m.role === 'user') turns.push({ role: 'user', content: m.content })
    else if (m.role === 'assistant' && !m.refused) turns.push({ role: 'assistant', content: m.content })
  }
  return turns.slice(-HISTORY_TURNS)
}
