import * as Dialog from '@radix-ui/react-dialog'
import { useMutation } from '@tanstack/react-query'
import { MessageSquareText, Send, ShieldAlert, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import type { components } from '@/api/schema'
import { Button } from '@/components/ui/Button'
import { api, unwrap } from '@/lib/api'
import { cn } from '@/lib/cn'

type Citation = components['schemas']['CitationOut']
import { historyFor, type Turn } from '@/lib/chatHistory'

type Message =
  | { role: 'user'; content: string }
  | { role: 'assistant'; content: string; citations: Citation[]; refused: boolean }
  | { role: 'error'; content: string }

const SUGGESTIONS = ['What are customers struggling with most?', 'Which problems affect enterprise customers?', 'What do people like about the product?']
/** A floating button that opens a side panel for quick questions about the active campaign's approved sources. */
export function QuickChat({ campaignId, disabled }: { campaignId: string | null | undefined; disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [question, setQuestion] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  const ask = useMutation({
    mutationFn: (q: { text: string; history: Turn[] }) =>
      unwrap(api.POST('/api/v1/chat', { body: { campaign_id: campaignId!, question: q.text, history: q.history } })),
  })

  useEffect(() => endRef.current?.scrollIntoView?.({ block: 'end' }), [messages, ask.isPending])

  async function send(text: string) {
    const trimmed = text.trim()
    if (trimmed.length < 3 || !campaignId || ask.isPending) return
    const history = historyFor(messages)
    setMessages((m) => [...m, { role: 'user', content: trimmed }])
    setQuestion('')
    try {
      const r = await ask.mutateAsync({ text: trimmed, history })
      setMessages((m) => [...m, { role: 'assistant', content: r.refused ? (r.message ?? 'I could not find that in your sources.') : (r.answer ?? ''), citations: r.citations, refused: r.refused }])
    } catch (e) {
      setMessages((m) => [...m, { role: 'error', content: e instanceof Error ? e.message : 'Something went wrong. Please try again.' }])
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    void send(question)
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          disabled={disabled}
          className="fixed right-5 bottom-5 z-30 flex h-12 items-center gap-2 rounded-full bg-ink px-5 text-sm font-medium text-ink-contrast shadow-lift transition-transform hover:-translate-y-0.5 disabled:opacity-50"
        >
          <MessageSquareText className="size-4" aria-hidden />
          Ask your data
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col border-l border-line bg-card shadow-lift outline-none">
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <div>
              <Dialog.Title className="text-base font-semibold text-ink">Ask your data</Dialog.Title>
              <Dialog.Description className="text-xs text-muted">Answers come only from your approved sources, with the quote behind them.</Dialog.Description>
            </div>
            <Dialog.Close aria-label="Close" className="grid size-9 place-items-center rounded-full text-muted hover:bg-inner hover:text-ink">
              <X className="size-4" aria-hidden />
            </Dialog.Close>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4" aria-live="polite">
            {messages.length === 0 && (
              <div>
                <p className="mb-3 text-sm text-muted">Try asking:</p>
                <div className="flex flex-col gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} type="button" onClick={() => send(s)} className="rounded-inner bg-inner px-4 py-3 text-left text-sm text-ink transition-colors hover:bg-line">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-ink px-4 py-2.5 text-sm text-ink-contrast">
                  {m.content}
                </div>
              ) : m.role === 'error' ? (
                <p key={i} role="alert" className="rounded-inner bg-negative-tint px-4 py-3 text-sm text-negative">
                  {m.content}
                </p>
              ) : (
                <div key={i} className={cn('max-w-[92%] rounded-2xl rounded-bl-md px-4 py-3 text-sm', m.refused ? 'bg-warning-tint text-ink' : 'bg-inner text-ink')}>
                  {m.refused && (
                    <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-warning">
                      <ShieldAlert className="size-3.5" aria-hidden /> Not in your sources
                    </p>
                  )}
                  <p className="whitespace-pre-wrap">{m.content}</p>
                  {m.citations.length > 0 && (
                    <ol className="mt-3 space-y-2 border-t border-line pt-3">
                      {m.citations.map((c) => (
                        <li key={c.n} className="text-xs text-muted">
                          <span className="font-medium text-ink">
                            [{c.n}] {c.resource_title}
                          </span>
                          <span className="mt-0.5 block italic">“{c.snippet}”</span>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              ),
            )}
            {ask.isPending && (
              <p role="status" className="text-sm text-muted">
                Reading your sources…
              </p>
            )}
            <div ref={endRef} />
          </div>

          <form onSubmit={submit} className="flex items-center gap-2 border-t border-line p-4">
            <input
              aria-label="Your question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about your customers…"
              maxLength={1000}
              className="h-11 min-w-0 flex-1 rounded-full border border-line bg-inner px-4 text-sm text-ink outline-none placeholder:text-muted focus:border-accent"
            />
            <Button type="submit" aria-label="Send" disabled={question.trim().length < 3 || ask.isPending} className="size-11 shrink-0 px-0">
              <Send className="size-4" aria-hidden />
            </Button>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
