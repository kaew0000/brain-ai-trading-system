/**
 * MiniChart — small dependency-free SVG line chart.
 *
 * V16 Track W14-1 Item 12 (Train Monitor history graph). No charting
 * library exists in this project (see dashboard_src/package.json —
 * only clsx/framer-motion beyond React itself), so this follows the
 * codebase's existing convention (see ConfBar/BreakdownBars in
 * components/common/index.tsx) of small hand-rolled SVG widgets rather
 * than introducing a new dependency for one chart.
 *
 * Pure presentation: takes already-fetched numeric series, no data
 * fetching, no API calls. Renders nothing (not an error) when given
 * fewer than 2 points, since a single point can't draw a trend line —
 * same "honest empty state, not fabricated data" posture as Empty/
 * Loading elsewhere in this file.
 */
import clsx from 'clsx'

export interface MiniChartSeries {
  label: string
  color: string // tailwind stroke color class isn't usable inline on SVG; pass a hex/CSS color
  values: number[]
}

export function MiniChart({
  series,
  height = 120,
  formatValue,
}: {
  series: MiniChartSeries[]
  height?: number
  formatValue?: (v: number) => string
}) {
  const allValues = series.flatMap(s => s.values)
  if (allValues.length < 2 || series.every(s => s.values.length < 2)) {
    return <div className="flex items-center justify-center text-text-muted text-xs" style={{ height }}>Not enough history yet</div>
  }

  const min = Math.min(...allValues)
  const max = Math.max(...allValues)
  const range = max - min || 1
  const width = 100 // viewBox units; scales to container via SVG width=100%
  const pad = 4

  const toPoints = (values: number[]) => {
    const n = values.length
    return values
      .map((v, i) => {
        const x = n === 1 ? width / 2 : (i / (n - 1)) * (width - pad * 2) + pad
        const y = height - pad - ((v - min) / range) * (height - pad * 2)
        return `${x},${y}`
      })
      .join(' ')
  }

  const last = (values: number[]) => values[values.length - 1]

  return (
    <div>
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none">
        {series.map(s => (
          s.values.length >= 2 && (
            <polyline
              key={s.label}
              points={toPoints(s.values)}
              fill="none"
              stroke={s.color}
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
            />
          )
        ))}
      </svg>
      <div className="flex flex-wrap gap-3 mt-2">
        {series.map(s => (
          <div key={s.label} className="flex items-center gap-1.5 text-[10px] font-mono">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
            <span className="text-text-muted">{s.label}</span>
            <span className={clsx('text-text-secondary')}>
              {s.values.length ? (formatValue ? formatValue(last(s.values)) : last(s.values)) : '—'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
