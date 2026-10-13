import { useLayoutEffect, useRef, useState } from 'react'
import type { OverviewBucket } from '../api/client'
import { compactMoney } from '../format'

export type ChartMetric = 'spent-revenue' | 'profit'

const HEIGHT = 250
const LEFT = 52
const RIGHT = 8
const TOP = 16
const BOTTOM = 28
const SPENT_COLOR = 'var(--accent-cyan)'
const GAIN_COLOR = 'var(--status-success)'
const LOSS_COLOR = 'var(--status-failed)'

function fullMoney(n: number): string {
  return `${n < 0 ? '-' : ''}$${Math.abs(Math.round(n)).toLocaleString()}`
}

/** Axis ticks at a round step, covering [min, max] in at most ~5 lines. */
function niceTicks(min: number, max: number): { ticks: number[]; low: number; high: number } {
  const span = Math.max(max - min, 1)
  const rough = span / 4
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rough) ?? 10 * magnitude
  const low = Math.floor(min / step) * step
  const high = Math.ceil(max / step) * step
  const ticks: number[] = []
  for (let v = low; v <= high + step / 2; v += step) ticks.push(Math.round(v * 100) / 100)
  return { ticks, low, high }
}

/** The chart's width in real pixels, so text stays a constant size. */
function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(640)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setWidth(entry.contentRect.width)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, width]
}

/**
 * Bars per week or month, on a real dollar scale with gridlines, so you can
 * read amounts off it instead of guessing from a line's height. Spent vs.
 * revenue draws two bars per bucket; profit draws one (red when negative).
 */
function OverviewChart({ buckets, metric }: { buckets: OverviewBucket[]; metric: ChartMetric }): React.JSX.Element {
  const [ref, width] = useWidth()
  const series =
    metric === 'spent-revenue'
      ? [buckets.map((b) => b.spent), buckets.map((b) => b.revenue)]
      : [buckets.map((b) => b.profit)]
  const all = series.flat()
  const { ticks, low, high } = niceTicks(Math.min(0, ...all), Math.max(0, ...all, 1))
  const plotW = width - LEFT - RIGHT
  const plotH = HEIGHT - TOP - BOTTOM
  const groupW = plotW / Math.max(buckets.length, 1)
  const barW = Math.max(6, Math.min(metric === 'spent-revenue' ? 34 : 48, (groupW - 10) / series.length))
  const y = (v: number): number => TOP + plotH - ((v - low) / (high - low)) * plotH
  const zero = y(0)
  const showValues = barW >= 26

  return (
    <div ref={ref} style={{ width: '100%' }}>
      <svg width={width} height={HEIGHT} role="img" aria-label={metric === 'profit' ? 'Profit' : 'Spent versus revenue'}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={LEFT} x2={width - RIGHT} y1={y(t)} y2={y(t)} stroke="var(--divider)" strokeWidth={t === 0 ? 1 : 0.6} />
            <text x={LEFT - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--text-faint)" fontFamily="var(--font-mono)">
              {t < 0 ? '-' : ''}
              {compactMoney(t)}
            </text>
          </g>
        ))}
        {buckets.map((b, i) => {
          const center = LEFT + groupW * i + groupW / 2
          return (
            <g key={b.key}>
              {series.map((s, j) => {
                const v = s[i]
                const x = series.length === 2 ? center - barW - 2 + j * (barW + 4) : center - barW / 2
                const color = metric === 'profit' ? (v < 0 ? LOSS_COLOR : GAIN_COLOR) : j === 0 ? SPENT_COLOR : GAIN_COLOR
                const top = Math.min(y(v), zero)
                const h = Math.abs(y(v) - zero)
                const label = `${b.label}${b.partial ? ' (so far)' : ''}: ${fullMoney(v)}`
                if (v === 0) {
                  return <line key={j} x1={x} x2={x + barW} y1={zero - 1} y2={zero - 1} stroke={color} strokeWidth={1.5} opacity={0.35} />
                }
                return (
                  <g key={j}>
                    <rect x={x} y={top} width={barW} height={Math.max(h, 1)} rx={3} fill={color}>
                      <title>{label}</title>
                    </rect>
                    {showValues && (
                      <text
                        x={x + barW / 2}
                        y={v < 0 ? top + h + 13 : top - 5}
                        textAnchor="middle"
                        fontSize={11}
                        fill="var(--text-secondary)"
                        fontFamily="var(--font-mono)"
                      >
                        {compactMoney(v)}
                      </text>
                    )}
                  </g>
                )
              })}
              <text x={center} y={HEIGHT - 8} textAnchor="middle" fontSize={11.5} fill="var(--text-faint)">
                {b.label}
                {b.partial ? ' *' : ''}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}

export default OverviewChart
