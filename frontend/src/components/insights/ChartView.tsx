import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis, LabelList } from 'recharts'
import { clip, colorsFor, foldSlices, formatValue, isHorizontal, shortWeek, toRows, type ChartResult, type ChartSpec } from '@/lib/charts'

const TICK = { fill: 'var(--muted)', fontSize: 11 }
const HEIGHT = 280

/** The hover card: the category, then each series with its colour and value. Uses the card's own colours so it works in both themes. */
type TipProps = {
  active?: boolean
  payload?: ReadonlyArray<{ dataKey?: unknown; name?: unknown; value?: unknown; color?: string; payload?: { fill?: string } }>
  label?: unknown
  measure: string
}

export function ChartTooltip({ active, payload, label, measure }: TipProps) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-inner border border-line bg-card px-3 py-2 text-xs shadow-lift">
      {label != null && <p className="mb-1 font-medium text-ink">{shortWeek(String(label))}</p>}
      <ul className="space-y-0.5">
        {payload.map((p) => (
          <li key={String(p.dataKey ?? p.name)} className="flex items-center gap-2 text-muted">
            <span className="size-2 rounded-full" style={{ background: p.color ?? p.payload?.fill }} aria-hidden />
            <span>{String(p.name ?? '')}</span>
            <span className="ml-auto pl-3 font-medium text-ink tabular-nums">{formatValue(Number(p.value))}</span>
          </li>
        ))}
      </ul>
      <p className="mt-1 text-[10px] text-muted">{measure}</p>
    </div>
  )
}

/** One chart drawn from a spec and its result: bar, stacked bar, line or pie. Thin marks, no clutter, labels on the bars. */
export function ChartView({ spec, result }: { spec: ChartSpec; result: ChartResult }) {
  const names = result.series.map((s) => s.name)
  const colors = colorsFor(names)
  const rows = toRows(result)
  const tip = <Tooltip cursor={{ fill: 'var(--card-inner)', opacity: 0.6 }} content={(p) => <ChartTooltip active={p.active} payload={p.payload} label={p.label} measure={result.measure} />} />
  const tickFormat = (v: string) => clip(spec.x === 'week' ? shortWeek(v) : v, 18)

  if (spec.type === 'pie') {
    const folded = foldSlices(result)
    const sliceColors = colorsFor(folded.x.map((_, i) => `slice${i}`))
    const data = folded.x.map((x, i) => ({ name: x, value: folded.series[0]?.values[i] ?? 0, fill: sliceColors[i] }))
    return (
      <ResponsiveContainer width="100%" height={HEIGHT}>
        <PieChart>
          <Pie isAnimationActive={false} data={data} dataKey="value" nameKey="name" innerRadius="46%" outerRadius="70%" paddingAngle={2} stroke="var(--card)" strokeWidth={2} label={({ name, percent }) => `${clip(String(name), 12)} ${Math.round((percent ?? 0) * 100)}%`} labelLine={false}>
            {data.map((d) => (
              <Cell key={d.name} fill={d.fill} />
            ))}
          </Pie>
          {tip}
        </PieChart>
      </ResponsiveContainer>
    )
  }

  if (spec.type === 'line') {
    return (
      <ResponsiveContainer width="100%" height={HEIGHT}>
        <LineChart data={rows} margin={{ top: 12, right: 16, bottom: 0, left: -12 }}>
          <CartesianGrid vertical={false} stroke="var(--line)" />
          <XAxis dataKey="x" tick={TICK} tickLine={false} axisLine={{ stroke: 'var(--line)' }} tickFormatter={tickFormat} minTickGap={16} />
          <YAxis tick={TICK} tickLine={false} axisLine={false} allowDecimals={false} />
          {tip}
          {names.map((n, i) => (
            <Line key={n} isAnimationActive={false} type="monotone" dataKey={n} stroke={colors[i]} strokeWidth={2} dot={{ r: 3, fill: colors[i], stroke: 'var(--card)', strokeWidth: 2 }} activeDot={{ r: 5 }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    )
  }

  const stacked = spec.type === 'stacked_bar' || names.length > 1
  const horizontal = isHorizontal(result, spec.x)
  const radius: [number, number, number, number] = horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]
  return (
    <ResponsiveContainer width="100%" height={horizontal ? Math.max(HEIGHT, rows.length * 34 + 40) : HEIGHT}>
      <BarChart data={rows} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: horizontal ? 8 : 22, right: 28, bottom: 0, left: horizontal ? 0 : -12 }} barCategoryGap="28%">
        {!horizontal && <CartesianGrid vertical={false} stroke="var(--line)" />}
        {horizontal ? (
          <>
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="x" width={132} tick={TICK} tickLine={false} axisLine={false} tickFormatter={tickFormat} />
          </>
        ) : (
          <>
            <XAxis dataKey="x" tick={TICK} tickLine={false} axisLine={{ stroke: 'var(--line)' }} tickFormatter={tickFormat} interval={0} />
            <YAxis tick={TICK} tickLine={false} axisLine={false} allowDecimals={false} />
          </>
        )}
        {tip}
        {names.map((n, i) => (
          <Bar key={n} isAnimationActive={false} dataKey={n} stackId={stacked ? 'a' : undefined} fill={colors[i]} stroke="var(--card)" strokeWidth={stacked ? 2 : 0} radius={stacked && i < names.length - 1 ? 0 : radius} maxBarSize={28}>
            {names.length === 1 && <LabelList dataKey={n} position={horizontal ? 'right' : 'top'} formatter={(v: unknown) => formatValue(Number(v))} style={{ fill: 'var(--ink)', fontSize: 11 }} />}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}
