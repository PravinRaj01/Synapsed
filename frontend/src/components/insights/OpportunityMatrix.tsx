import { useMemo, useState } from 'react'
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import { Card, CardTitle } from '@/components/ui/Card'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { plotPoints, quadrantCorners, type OpportunityMatrix as Matrix, type PlotPoint } from '@/lib/charts'

type View = 'chart' | 'table'

const CORNER: Record<'tl' | 'tr' | 'bl' | 'br', string> = { tl: 'top-2 left-14', tr: 'top-2 right-8 text-right', bl: 'bottom-9 left-14', br: 'bottom-9 right-8 text-right' }

/** A dot with its rank written inside, so the dots can be told apart without labels crowding the plot. */
function RankDot({ cx = 0, cy = 0, payload }: { cx?: number; cy?: number; payload?: PlotPoint }) {
  return (
    <g>
      <circle cx={cx} cy={cy} r={11} fill="var(--series-1)" stroke="var(--card)" strokeWidth={2} />
      <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central" fontSize={11} fontWeight={600} fill="#fff">
        {payload?.rank}
      </text>
    </g>
  )
}

/** Every theme placed by how often it was mentioned (across) and its business impact (up). The dashed lines split the four quadrants. */
export function OpportunityMatrix({ matrix }: { matrix: Matrix }) {
  const [view, setView] = useState<View>('chart')
  const points = useMemo(() => plotPoints(matrix.points), [matrix.points])
  const maxX = Math.max(matrix.frequency_line + 1, ...points.map((p) => p.shownX)) + 1

  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <CardTitle>Opportunity matrix</CardTitle>
          <p className="mt-0.5 text-xs text-muted">Themes by how often customers raised them and how much it matters. Top right is where to start.</p>
        </div>
        <SegmentedControl<View> label="Opportunity matrix: chart or table" value={view} onChange={setView} options={[{ value: 'chart', label: 'Chart' }, { value: 'table', label: 'Table' }]} className="[&_button]:px-3 [&_button]:py-1 [&_button]:text-xs" />
      </div>

      {view === 'chart' ? (
        <>
          <div className="relative mt-4">
            {quadrantCorners(matrix).map((q) => (
              <span key={q.key} className={`pointer-events-none absolute z-10 max-w-[9rem] text-[10px] leading-tight text-muted ${CORNER[q.corner]}`}>
                {q.label}
              </span>
            ))}
            <ResponsiveContainer width="100%" height={340}>
              <ScatterChart margin={{ top: 16, right: 24, bottom: 8, left: 0 }}>
                <CartesianGrid stroke="var(--line)" />
                <XAxis type="number" dataKey="shownX" name="Mentions" domain={[0, maxX]} allowDecimals={false} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={{ stroke: 'var(--line)' }} label={{ value: 'Mentions', position: 'insideBottom', offset: -2, fill: 'var(--muted)', fontSize: 11 }} />
                <YAxis type="number" dataKey="y" name="Business impact" domain={[0, 100]} tick={{ fill: 'var(--muted)', fontSize: 11 }} tickLine={false} axisLine={false} width={44} label={{ value: 'Impact', angle: -90, position: 'insideLeft', fill: 'var(--muted)', fontSize: 11 }} />
                <ZAxis range={[200, 200]} />
                <ReferenceLine x={matrix.frequency_line} stroke="var(--muted)" strokeDasharray="4 4" />
                <ReferenceLine y={matrix.impact_line} stroke="var(--muted)" strokeDasharray="4 4" />
                <Tooltip
                  cursor={{ strokeDasharray: '3 3', stroke: 'var(--muted)' }}
                  content={({ active, payload }) => {
                    const p = active ? (payload?.[0]?.payload as PlotPoint | undefined) : undefined
                    if (!p) return null
                    return (
                      <div className="rounded-inner border border-line bg-card px-3 py-2 text-xs shadow-lift">
                        <p className="mb-1 font-medium text-ink">{p.rank}. {p.label}</p>
                        <p className="text-muted">{p.frequency} {p.frequency === 1 ? 'mention' : 'mentions'}, impact {p.y}</p>
                        <p className="text-muted">{p.quadrant_label}</p>
                        {p.horizon && <p className="text-muted">On the roadmap: {p.horizon}</p>}
                      </div>
                    )
                  }}
                />
                <Scatter isAnimationActive={false} data={points} shape={(props: unknown) => <RankDot {...(props as { cx?: number; cy?: number; payload?: PlotPoint })} />} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <ol className="mt-3 grid gap-x-6 gap-y-1.5 sm:grid-cols-2" aria-label="Themes in the matrix">
            {points.map((p) => (
              <li key={p.theme_id} className="flex items-center gap-2 text-xs text-ink">
                <span className="grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold text-white" style={{ background: 'var(--series-1)' }} aria-hidden>{p.rank}</span>
                <span className="min-w-0 flex-1 truncate">{p.label}</span>
                <span className="shrink-0 text-muted tabular-nums">{p.frequency} · {p.y}</span>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Opportunity matrix</caption>
            <thead className="text-xs text-muted">
              <tr className="border-b border-line">
                <th scope="col" className="py-2 pr-4 font-medium">Theme</th>
                <th scope="col" className="py-2 pr-4 font-medium">Quadrant</th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">Mentions</th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">Impact</th>
                <th scope="col" className="py-2 pr-4 text-right font-medium">ICE</th>
                <th scope="col" className="py-2 font-medium">Roadmap</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.theme_id} className="border-b border-line last:border-0">
                  <th scope="row" className="py-2 pr-4 font-normal text-ink">{p.label}</th>
                  <td className="py-2 pr-4 text-muted">{p.quadrant_label}</td>
                  <td className="py-2 pr-4 text-right tabular-nums text-ink">{p.frequency}</td>
                  <td className="py-2 pr-4 text-right tabular-nums text-ink">{p.y}</td>
                  <td className="py-2 pr-4 text-right tabular-nums text-ink">{p.ice_score ?? '–'}</td>
                  <td className="py-2 text-muted">{p.horizon ?? '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
