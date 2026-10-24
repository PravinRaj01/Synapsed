import { evidenceByNumber, storyEvidence, type Prd } from '@/lib/board'

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <section>
      <h3 className="mb-1.5 text-sm font-semibold text-ink">{title}</h3>
      <ul className="list-disc space-y-1 pl-5 text-sm text-ink">
        {items.map((t, i) => (
          <li key={i}>{t}</li>
        ))}
      </ul>
    </section>
  )
}

/** A PRD laid out to read: the problem, goals, user stories with the customer quotes behind them, and how success is judged. */
export function PrdDocument({ prd }: { prd: Prd }) {
  const body = prd.content.prd
  const evidence = evidenceByNumber(prd)
  return (
    <article className="space-y-6">
      <header>
        <h2 className="text-xl font-semibold tracking-tight text-ink">{body.title}</h2>
        <p className="mt-1 text-xs text-muted">Written {new Date(prd.created_at).toLocaleDateString(undefined, { day: 'numeric', month: 'long', year: 'numeric' })} from {prd.content.evidence.length} pieces of customer evidence</p>
      </header>
      <section>
        <h3 className="mb-1.5 text-sm font-semibold text-ink">Context</h3>
        <p className="text-sm text-ink">{body.context}</p>
      </section>
      <section>
        <h3 className="mb-1.5 text-sm font-semibold text-ink">Problem</h3>
        <p className="text-sm text-ink">{body.problem}</p>
      </section>
      <List title="Goals" items={body.goals} />
      {body.user_stories.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-ink">User stories</h3>
          <ol className="space-y-3">
            {body.user_stories.map((s, i) => {
              const quotes = storyEvidence(s, evidence)
              return (
                <li key={i} className="rounded-inner bg-inner p-4 text-sm text-ink print:border print:border-neutral-300 print:bg-white">
                  <p>
                    As <strong>{s.as_a}</strong>, I want <strong>{s.i_want}</strong> so that <strong>{s.so_that}</strong>.
                  </p>
                  {quotes.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {quotes.map((q) => (
                        <li key={q.n} className="text-xs text-muted">
                          <span className="font-medium text-ink">[{q.n}]</span> <span className="italic">“{q.quote}”</span> <span>· {q.resource_title}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              )
            })}
          </ol>
        </section>
      )}
      <List title="Acceptance criteria" items={body.acceptance_criteria} />
      <List title="Out of scope" items={body.out_of_scope} />
      <List title="How we will know it worked" items={body.success_metrics} />
      {prd.content.evidence.length > 0 && (
        <section>
          <h3 className="mb-2 text-sm font-semibold text-ink">Evidence</h3>
          <ol className="space-y-2">
            {prd.content.evidence.map((e) => (
              <li key={e.n} className="text-xs text-muted">
                <span className="font-medium text-ink">[{e.n}] {e.summary}</span>
                <span className="block italic">“{e.quote}”</span>
                <span>
                  {e.resource_title}
                  {e.segment ? ` · ${e.segment}` : ''} · severity {e.severity}/5
                </span>
              </li>
            ))}
          </ol>
        </section>
      )}
    </article>
  )
}
