import { useEffect, useMemo, useRef } from 'react'
import type { Focus } from '@/lib/chat'
import { withFocus } from '@/lib/chat'
import { highlightPieces, type Highlight } from '@/lib/vaultLogic'

/**
 * A source's text with the quotes behind pain points highlighted in their theme's colour. One quote can be in focus:
 * it is scrolled to the middle and flashes (`focusKey` changes each time the same quote is asked for again).
 */
export function HighlightedText({ content, highlights, focus = null, focusKey = 0 }: { content: string; highlights: Highlight[]; focus?: Focus | null; focusKey?: number }) {
  const pieces = useMemo(() => highlightPieces(content, withFocus(highlights, focus)), [content, highlights, focus])
  const focused = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (focus) focused.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' }) // no arrow shorthand: an effect must not return a value
  }, [focus, focusKey, content])

  return (
    <div className="rounded-inner bg-inner p-4 text-sm leading-relaxed whitespace-pre-wrap text-ink" data-testid="source-text">
      {pieces.map((p, i) => {
        const h = p.highlight
        if (!h) return <span key={i}>{p.text}</span>
        if (h.focus) {
          return (
            <mark key={`${i}-${focusKey}`} ref={focused} data-focus className="focus-flash rounded px-0.5 text-ink">
              {p.text}
            </mark>
          )
        }
        const color = h.color ?? 'var(--accent)'
        return (
          <mark
            key={i}
            title={h.theme ? `${h.theme}: ${h.insight}` : h.insight}
            className="rounded px-0.5 text-ink"
            style={{ background: `color-mix(in srgb, ${color} 28%, transparent)`, boxShadow: `inset 0 -2px 0 ${color}` }}
          >
            {p.text}
          </mark>
        )
      })}
    </div>
  )
}
