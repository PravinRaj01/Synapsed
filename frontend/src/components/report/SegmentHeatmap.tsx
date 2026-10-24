import { Card, CardTitle } from '@/components/ui/Card'
import { buildHeatmap, cellStrength, shortSegment } from '@/lib/report'
import type { ThemeRow } from '@/lib/vault'

/**
 * Which customer groups raise which problems: themes down the side, segments across the top, the number of pain
 * points in every cell. Darker means more, but the number is always written, so colour is never the only cue.
 */
export function SegmentHeatmap({ themes }: { themes: ThemeRow[] }) {
  const { columns, rows, max } = buildHeatmap(themes)
  if (columns.length === 0) return null
  return (
    <Card>
      <CardTitle>Who raises what</CardTitle>
      <p className="mt-0.5 text-xs text-muted">Pain points and requests by theme and customer segment. Darker means more.</p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full table-fixed border-separate border-spacing-1 text-sm sm:min-w-[480px]">
          <caption className="sr-only">Pain points by theme and customer segment</caption>
          <thead>
            <tr>
              <th scope="col" className="w-[7.5rem] px-2 py-1.5 text-left text-xs font-medium text-muted sm:w-1/3">Theme</th>
              {columns.map((c) => (
                <th key={c.key} scope="col" className="px-2 py-1.5 text-center text-xs font-medium text-muted">
                  <span className="block truncate sm:hidden" aria-hidden title={c.name}>{shortSegment(c.name)}</span>
                  <span className="sr-only sm:not-sr-only sm:block sm:truncate">{c.name}</span>
                </th>
              ))}
              <th scope="col" className="w-12 px-2 py-1.5 text-right text-xs font-medium text-muted">Total</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.theme.id}>
                <th scope="row" className="px-2 py-1.5 text-left font-normal text-ink">
                  <span className="flex min-w-0 items-center gap-2" title={r.theme.label}>
                    <span className="size-2 shrink-0 rounded-full" style={{ background: r.theme.color }} aria-hidden />
                    <span className="truncate">{r.theme.label}</span>
                  </span>
                </th>
                {r.cells.map((n, i) => {
                  const strength = cellStrength(n, max)
                  return (
                    <td
                      key={columns[i].key}
                      title={`${r.theme.label}, ${columns[i].name}: ${n} ${n === 1 ? 'pain point' : 'pain points'}`}
                      className="rounded-inner px-2 py-2 text-center tabular-nums"
                      style={{ background: strength ? `color-mix(in srgb, var(--accent-from) ${Math.round(strength * 70)}%, transparent)` : 'var(--card-inner)', color: strength > 0.7 ? '#fff' : 'var(--ink)' }}
                    >
                      {n || <span className="text-muted">–</span>}
                    </td>
                  )
                })}
                <td className="px-2 py-1.5 text-right tabular-nums text-muted">{r.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
