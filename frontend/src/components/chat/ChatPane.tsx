import { Eraser, Send, ShieldAlert } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/cn'
import { splitFootnotes, type ChatMessage, type Citation, type Focus } from '@/lib/chat'

export type OpenSource = (resourceId: string, focus: Focus | null) => void

const SUGGESTIONS = ['What are customers struggling with most?', 'Which problems affect enterprise customers?', 'What do people like about the product?', 'What did customers ask us to build?']

/** One footnote marker: a button that opens the quote it points at, or plain text when the answer cites a source that was not returned. */
function Footnote({ n, citations, onOpen }: { n: number; citations: Citation[]; onOpen: OpenSource }) {
  const c = citations.find((x) => x.n === n)
  if (!c) return <span className="text-muted">[{n}]</span>
  return (
    <button
      type="button"
      onClick={() => onOpen(c.resource_id, c.verified ? { start: c.start_offset, end: c.end_offset } : null)}
      aria-label={`Show source ${n}: ${c.resource_title}`}
      className="mx-0.5 inline-grid h-5 min-w-5 place-items-center rounded-full bg-accent-tint px-1 align-baseline text-[11px] font-semibold text-accent transition-colors hover:bg-accent hover:text-white"
    >
      {n}
    </button>
  )
}

function Assistant({ m, onOpen }: { m: Extract<ChatMessage, { role: 'assistant' }>; onOpen: OpenSource }) {
  return (
    <div className={cn('max-w-[95%] rounded-2xl rounded-bl-md px-4 py-3 text-sm', m.refused ? 'bg-warning-tint text-ink' : 'bg-inner text-ink')}>
      {m.refused && (
        <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-warning">
          <ShieldAlert className="size-3.5" aria-hidden /> Not in your sources
        </p>
      )}
      <p className="whitespace-pre-wrap">
        {splitFootnotes(m.content).map((part, i) => (part.type === 'text' ? <span key={i}>{part.text}</span> : <Footnote key={i} n={part.n} citations={m.citations} onOpen={onOpen} />))}
      </p>
      {m.citations.length > 0 && (
        <ol className="mt-3 space-y-2 border-t border-line pt-3">
          {m.citations.map((c) => (
            <li key={c.n} className="text-xs text-muted">
              <button type="button" onClick={() => onOpen(c.resource_id, c.verified ? { start: c.start_offset, end: c.end_offset } : null)} className="text-left font-medium text-ink hover:underline">
                [{c.n}] {c.resource_title}
              </button>
              <span className="mt-0.5 block italic">“{c.snippet}”</span>
              {!c.verified && <span className="mt-0.5 block text-warning">The exact words could not be located; this is the passage it came from.</span>}
            </li>
          ))}
        </ol>
      )}
      {(m.model || m.passages > 0) && (
        <p className="mt-3 text-[11px] text-muted" data-testid="telemetry">
          {[m.model, m.tokens ? `${m.tokens.toLocaleString()} tokens` : null, `${m.passages} ${m.passages === 1 ? 'passage' : 'passages'} read`].filter(Boolean).join(' · ')}
        </p>
      )}
    </div>
  )
}

type Props = {
  messages: ChatMessage[]
  pending: boolean
  blocked: string | null
  scope: string
  onAsk: (question: string) => Promise<boolean>
  onClear: () => void
  onOpen: OpenSource
}

/** The conversation: questions, answers with clickable footnotes, refusals and errors, and the box to ask more. */
export function ChatPane({ messages, pending, blocked, scope, onAsk, onClear, onOpen }: Props) {
  const [question, setQuestion] = useState('')
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'end' }) // an effect must return nothing or a clean-up function
  }, [messages.length, pending])

  async function send(text: string) {
    if (blocked) return
    setQuestion('')
    await onAsk(text)
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    void send(question)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">Ask your sources</h2>
          <p className="text-xs text-muted">{scope}</p>
        </div>
        {messages.length > 0 && (
          <button type="button" onClick={onClear} className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs text-muted hover:bg-inner hover:text-ink">
            <Eraser className="size-3.5" aria-hidden /> Clear
          </button>
        )}
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4" aria-live="polite">
        {messages.length === 0 && (
          <div>
            <p className="mb-3 text-sm text-muted">Every answer comes with the customer's own words. Try asking:</p>
            <div className="flex flex-col gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" disabled={!!blocked || pending} onClick={() => send(s)} className="rounded-inner bg-inner px-4 py-3 text-left text-sm text-ink transition-colors hover:bg-line disabled:opacity-50">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-sm text-ink-contrast">
              {m.content}
            </div>
          ) : m.role === 'error' ? (
            <p key={m.id} role="alert" className="rounded-inner bg-negative-tint px-4 py-3 text-sm text-negative">
              {m.content}
            </p>
          ) : (
            <Assistant key={m.id} m={m} onOpen={onOpen} />
          ),
        )}
        {pending && (
          <p role="status" className="text-sm text-muted">
            Reading your sources…
          </p>
        )}
        <div ref={end} />
      </div>

      <form onSubmit={submit} className="border-t border-line p-4">
        {blocked && <p className="mb-2 px-1 text-xs text-warning">{blocked}</p>}
        <div className="flex items-center gap-2">
          <input
            aria-label="Your question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about your customers…"
            maxLength={1000}
            disabled={!!blocked}
            className="h-11 min-w-0 flex-1 rounded-full border border-line bg-inner px-4 text-sm text-ink outline-none placeholder:text-muted focus:border-accent disabled:opacity-50"
          />
          <Button type="submit" aria-label="Send" disabled={!!blocked || question.trim().length < 3 || pending} className="size-11 shrink-0 px-0">
            <Send className="size-4" aria-hidden />
          </Button>
        </div>
      </form>
    </div>
  )
}
