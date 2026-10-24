import { X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { Card, CardTitle } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { axisLabel, colorsFor, describeSpec, foldSlices, hasData, toTable, type ChartResult, type ChartSpec } from '@/lib/charts'
import { ChartView } from './ChartView'

type View = 'chart' | 'table'

function Legend({ names, colors }: { names: string[]; colors: string[] }) {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5" aria-label="Legend">
      {names.map((n, i) => (
        <li key={n} className="flex items-center gap-1.5 text-xs text-ink">
          <span className="size-2.5 rounded-full" style={{ background: colors[i] }} aria-hidden />
          {n}
        </li>
      ))}
    </ul>
  )
}

/** A chart with its title, what it counts, a legend when there is more than one series, and a table view of the same numbers. */
export function ChartCard({ title, spec, result, note, onRemove, className }: { title: string; spec: ChartSpec; result: ChartResult; note?: ReactNode; onRemove?: () => void; className?: string }) {
  const [view, setView] = useState<View>('chart')
  const pie = spec.type === 'pie'
  const shown = pie ? foldSlices(result) : result
  const stacked = spec.type === 'stacked_bar' || result.series.length > 1
  const legendNames = pie ? shown.x : shown.series.map((s) => s.name)
  const legendColors = colorsFor(pie ? shown.x.map((_, i) => `slice${i}`) : legendNames)
  const table = toTable(shown, axisLabel(spec.x), stacked && spec.type !== 'line')

  return (
    <Card className={className}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle>{title}</CardTitle>
          <p className="mt-0.5 text-xs text-muted">{describeSpec(spec, result.measure)}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <SegmentedControl<View> label={`${title}: chart or table`} value={view} onChange={setView} options={[{ value: 'chart', label: 'Chart' }, { value: 'table', label: 'Table' }]} className="[&_button]:px-3 [&_button]:py-1 [&_button]:text-xs" />
          {onRemove && (
            <button type="button" onClick={onRemove} aria-label={`Remove ${title}`} className="grid size-8 place-items-center rounded-full text-muted hover:bg-inner hover:text-ink">
              <X className="size-4" aria-hidden />
            </button>
          )}
        </div>
      </div>

      <div className="mt-4">
        {!hasData(result) ? (
          <p className="py-12 text-center text-sm text-muted">Nothing to chart yet for this view.</p>
        ) : view === 'chart' ? (
          <>
            <ChartView spec={spec} result={result} />
            {(legendNames.length > 1 || pie) && <Legend names={legendNames} colors={legendColors} />}
          </>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{title}</caption>
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  {table.head.map((h, i) => (
                    <th key={h} scope="col" className={i === 0 ? 'py-2 pr-4 font-medium' : 'py-2 pr-4 text-right font-medium'}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.body.map((row) => (
                  <tr key={row[0]} className="border-b border-line last:border-0">
                    {row.map((cell, i) => (
                      i === 0 ? <th key={i} scope="row" className="py-2 pr-4 font-normal text-ink">{cell}</th> : <td key={i} className="py-2 pr-4 text-right tabular-nums text-ink">{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {note && <div className="mt-3 text-xs text-muted">{note}</div>}
    </Card>
  )
}
