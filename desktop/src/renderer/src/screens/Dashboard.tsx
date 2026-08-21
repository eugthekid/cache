import { useEffect, useMemo, useState } from 'react'
import {
  api,
  type AgingSummary,
  type CategoryBreakdown,
  type InventorySummary,
  type MonthlyPoint,
  type Order,
  type RetailerBreakdown
} from '../api/client'

type ChartMode = 'spending' | 'sales' | 'both'
type WidgetView = 'age' | 'retailer' | 'category'

const CHART_W = 620
const CHART_H = 180
const PAD_X = 20
const BASELINE = 150
const TOP = 14

/** Maps a series of numbers onto the chart's fixed viewBox, scaling to
 * that series' own max (or a shared max, when passed in) so a single-value
 * chart doesn't render as a flat line pinned to the top or bottom. */
function toPoints(values: number[], sharedMax?: number): { x: number; y: number }[] {
  const max = sharedMax ?? Math.max(...values, 1)
  const n = values.length
  const step = n > 1 ? (CHART_W - PAD_X * 2) / (n - 1) : 0
  return values.map((v, i) => ({
    x: PAD_X + step * i,
    y: BASELINE - (max > 0 ? (v / max) * (BASELINE - TOP) : 0)
  }))
}

function pointsToPath(points: { x: number; y: number }[]): string {
  return points.map((p) => `${p.x},${p.y}`).join(' ')
}

function monthLabel(month: string): string {
  const [, m] = month.split('-')
  const names = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  return names[parseInt(m, 10) - 1] ?? month
}

function currency(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function Dashboard(): React.JSX.Element {
  const [summary, setSummary] = useState<InventorySummary | null>(null)
  const [monthly, setMonthly] = useState<MonthlyPoint[]>([])
  const [aging, setAging] = useState<AgingSummary | null>(null)
  const [byRetailer, setByRetailer] = useState<RetailerBreakdown[]>([])
  const [byCategory, setByCategory] = useState<CategoryBreakdown[]>([])
  const [failedOrders, setFailedOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [chartMode, setChartMode] = useState<ChartMode>('spending')
  const [widgetView, setWidgetView] = useState<WidgetView>('age')

  useEffect(() => {
    let cancelled = false
    async function load(): Promise<void> {
      try {
        const [s, m, a, r, c, orders] = await Promise.all([
          api.inventory.summary(),
          api.dashboard.monthly(6),
          api.dashboard.aging(),
          api.dashboard.byRetailer(),
          api.dashboard.byCategory(),
          api.orders.list({ status: 'failed', limit: 5 })
        ])
        if (cancelled) return
        setSummary(s)
        setMonthly(m)
        setAging(a)
        setByRetailer(r)
        setByCategory(c)
        setFailedOrders(orders)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load dashboard')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [])

  const spendPoints = useMemo(() => toPoints(monthly.map((m) => m.spend)), [monthly])
  const revenuePoints = useMemo(() => toPoints(monthly.map((m) => m.revenue)), [monthly])
  const sharedMax = useMemo(
    () => Math.max(...monthly.map((m) => m.spend), ...monthly.map((m) => m.revenue), 1),
    [monthly]
  )
  const bothSpendPoints = useMemo(() => toPoints(monthly.map((m) => m.spend), sharedMax), [monthly, sharedMax])
  const bothRevenuePoints = useMemo(() => toPoints(monthly.map((m) => m.revenue), sharedMax), [monthly, sharedMax])

  const totalSpend6mo = monthly.reduce((sum, m) => sum + m.spend, 0)
  const totalRevenue6mo = monthly.reduce((sum, m) => sum + m.revenue, 0)
  const currentMonth = monthly[monthly.length - 1]

  if (loading) return <DashboardLoading />
  if (error) return <div style={{ color: 'var(--status-failed)' }}>Couldn't load the dashboard: {error}</div>

  return (
    <>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div className="screen-title">Dashboard</div>
        <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)' }}>
          {new Date().toISOString().slice(0, 10)}
        </div>
      </div>

      <div style={{ position: 'relative', display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 14 }}>
        <KpiCard label="Total spend" value={currency(summary?.total_cost_basis ?? 0)} sub={`${summary?.order_count ?? 0} orders`} accent />
        <KpiCard label="Est. inv. value" value={currency(summary?.est_inventory_value ?? 0)} sub={`${summary?.total_units ?? 0} units`} />
        <KpiCard label="In hand" value={String(summary?.in_hand ?? 0)} sub="units" />
        <KpiCard label="Listed" value={String(summary?.listed ?? 0)} sub="units" color="var(--status-warn)" />
        <KpiCard label="Sold" value={String(summary?.sold ?? 0)} sub="all time" color="var(--status-success)" />
      </div>

      <div style={{ position: 'relative', flex: 1, display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 16, minHeight: 0 }}>
        {/* Chart */}
        <div className="card" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>
              {chartMode === 'spending' ? 'Spending by month' : chartMode === 'sales' ? 'Sales by month' : 'Spending vs. sales'}
            </div>
            <div style={{ display: 'flex', gap: 4, background: 'var(--field-bg)', border: '1px solid var(--field-border)', borderRadius: 8, padding: 3 }}>
              {(['spending', 'sales', 'both'] as ChartMode[]).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setChartMode(mode)}
                  style={{
                    padding: '5px 13px',
                    borderRadius: 6,
                    fontSize: 11.5,
                    fontWeight: 600,
                    border: 'none',
                    cursor: 'pointer',
                    background: chartMode === mode ? 'var(--accent-gradient)' : 'transparent',
                    color: chartMode === mode ? 'oklch(14% 0.01 255)' : 'var(--text-secondary)'
                  }}
                >
                  {mode === 'spending' ? 'Spending' : mode === 'sales' ? 'Sales' : 'Both'}
                </button>
              ))}
            </div>
          </div>

          {chartMode !== 'both' && currentMonth && (
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
              <div className="num" style={{ fontSize: 28, fontWeight: 700 }}>
                {currency(chartMode === 'spending' ? currentMonth.spend : currentMonth.revenue)}
              </div>
              <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)', marginLeft: 'auto' }}>
                6-mo total {currency(chartMode === 'spending' ? totalSpend6mo : totalRevenue6mo)}
              </div>
            </div>
          )}
          {chartMode === 'both' && (
            <div style={{ display: 'flex', gap: 14 }}>
              <Legend color="var(--accent-cyan)" label="Spending" />
              <Legend color="var(--status-success)" label="Sales" />
            </div>
          )}

          {monthly.length === 0 ? (
            <EmptyChart />
          ) : (
            <>
              <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} preserveAspectRatio="none" style={{ width: '100%', flex: 1, minHeight: 0 }}>
                <line x1={PAD_X} y1={BASELINE} x2={CHART_W - PAD_X} y2={BASELINE} stroke="var(--divider)" strokeWidth="1" />
                {chartMode !== 'both' ? (
                  <ChartLine points={chartMode === 'spending' ? spendPoints : revenuePoints} color={chartMode === 'spending' ? 'var(--accent-cyan)' : 'var(--status-success)'} />
                ) : (
                  <>
                    <ChartLine points={bothSpendPoints} color="var(--accent-cyan)" />
                    <ChartLine points={bothRevenuePoints} color="var(--status-success)" />
                  </>
                )}
              </svg>
              <div style={{ display: 'flex', padding: '0 20px' }}>
                {monthly.map((m) => (
                  <span key={m.month} className="num" style={{ fontSize: 10.5, color: 'var(--text-faint)', flex: 1, textAlign: 'center' }}>
                    {monthLabel(m.month)}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>

        {/* Right column: aging/retailer/category widget + needs attention */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 }}>
          <div className="card" style={{ padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: 12, flex: 1, minHeight: 0, overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>How long you&rsquo;ve held it</div>
              <select className="select" style={{ width: 140 }} value={widgetView} onChange={(e) => setWidgetView(e.target.value as WidgetView)}>
                <option value="age">Inventory age</option>
                <option value="retailer">By retailer</option>
                <option value="category">By category</option>
              </select>
            </div>
            {widgetView === 'age' && aging && <AgingView aging={aging} />}
            {widgetView === 'retailer' && <RetailerView rows={byRetailer} />}
            {widgetView === 'category' && <CategoryView rows={byCategory} />}
          </div>

          <div className="card" style={{ padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: 10, flex: 0.85, minHeight: 0, overflow: 'hidden' }}>
            <div style={{ fontSize: 13.5, fontWeight: 600 }}>Needs attention</div>
            {failedOrders.length === 0 && (aging?.buckets[3].count ?? 0) === 0 ? (
              <div style={{ fontSize: 12.5, color: 'var(--text-faint)', margin: 'auto 0' }}>Nothing needs attention right now.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {failedOrders.length > 0 && (
                  <AttentionRow color="var(--status-failed)" text={`${failedOrders.length} order${failedOrders.length === 1 ? '' : 's'} failed — needs review`} />
                )}
                {(aging?.buckets[3].count ?? 0) > 0 && (
                  <AttentionRow
                    color="var(--status-warn)"
                    text={`${aging!.buckets[3].count} unit${aging!.buckets[3].count === 1 ? '' : 's'} held 60+ days (${currency(aging!.value_tied_up_60d_plus)} tied up)`}
                  />
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

function KpiCard({
  label,
  value,
  sub,
  accent,
  color
}: {
  label: string
  value: string
  sub: string
  accent?: boolean
  color?: string
}): React.JSX.Element {
  return (
    <div className="card" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 7 }}>
      <div className="label" style={color ? { color } : undefined}>
        {label}
      </div>
      <div
        className="num"
        style={{
          fontSize: 22,
          fontWeight: 700,
          color: color ?? 'var(--text-primary)',
          ...(accent
            ? {
                background: 'linear-gradient(120deg, oklch(85% 0.1 205), oklch(76% 0.15 292))',
                WebkitBackgroundClip: 'text',
                backgroundClip: 'text',
                WebkitTextFillColor: 'transparent'
              }
            : {})
        }}
      >
        {value}
      </div>
      <div className="num" style={{ fontSize: 11, color: 'var(--text-faint)' }}>
        {sub}
      </div>
    </div>
  )
}

function ChartLine({ points, color }: { points: { x: number; y: number }[]; color: string }): React.JSX.Element {
  if (points.length === 0) return <></>
  const path = pointsToPath(points)
  const areaPath = `${path} ${points[points.length - 1].x},${BASELINE} ${points[0].x},${BASELINE}`
  const gradId = `grad-${color.replace(/[^a-z]/gi, '')}`
  return (
    <>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={areaPath} fill={`url(#${gradId})`} />
      <polyline points={path} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      {points.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r={i === points.length - 1 ? 5 : 3.5}
          fill={i === points.length - 1 ? color : 'var(--card-bg)'}
          stroke={color}
          strokeWidth="2"
        />
      ))}
    </>
  )
}

function Legend({ color, label }: { color: string; label: string }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 14, height: 2.5, borderRadius: 2, background: color, display: 'inline-block' }} />
      <span className="num" style={{ fontSize: 11, color: 'var(--text-faint)' }}>
        {label}
      </span>
    </div>
  )
}

function AgingView({ aging }: { aging: AgingSummary }): React.JSX.Element {
  const gradients = [
    ['oklch(60% 0.13 150)', 'oklch(74% 0.17 150)'],
    ['oklch(58% 0.1 215)', 'oklch(78% 0.12 215)'],
    ['oklch(62% 0.11 85)', 'oklch(80% 0.15 85)'],
    ['oklch(55% 0.14 25)', 'oklch(74% 0.19 25)']
  ]
  const maxCount = Math.max(...aging.buckets.map((b) => b.count), 1)
  return (
    <>
      <div className="num" style={{ fontSize: 11, color: 'var(--text-faint)' }}>
        {aging.buckets.reduce((s, b) => s + b.count, 0)} units unsold
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-evenly' }}>
        {aging.buckets.map((bucket, i) => (
          <div key={bucket.label} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span className="num" style={{ fontSize: 10.5, color: i === 3 ? 'var(--status-failed)' : 'var(--text-faint)', width: 52, flexShrink: 0 }}>
              {bucket.label}
            </span>
            <div style={{ flex: 1, height: 20, background: 'oklch(15% 0.012 255 / 0.55)', borderRadius: 5, overflow: 'hidden' }}>
              <div
                style={{
                  width: `${(bucket.count / maxCount) * 100}%`,
                  height: '100%',
                  background: `linear-gradient(90deg, ${gradients[i][0]}, ${gradients[i][1]})`
                }}
              />
            </div>
            <span className="num" style={{ fontSize: 12, fontWeight: 600, width: 16, textAlign: 'right' }}>
              {bucket.count}
            </span>
          </div>
        ))}
      </div>
      <div style={{ paddingTop: 11, borderTop: '1px solid var(--divider)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>{currency(aging.value_tied_up_60d_plus)} tied up past 60 days</span>
      </div>
    </>
  )
}

const RETAILER_COLORS = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181']

function RetailerView({ rows }: { rows: RetailerBreakdown[] }): React.JSX.Element {
  if (rows.length === 0) return <EmptyMini text="No orders yet." />
  const max = Math.max(...rows.map((r) => r.order_count), 1)
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-evenly' }}>
      {rows.slice(0, 5).map((row, i) => (
        <div key={row.site} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 10.5, color: 'var(--text-secondary)', width: 100, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {row.site}
          </span>
          <div style={{ flex: 1, height: 18, background: 'oklch(15% 0.012 255 / 0.55)', borderRadius: 5, overflow: 'hidden' }}>
            <div style={{ width: `${(row.order_count / max) * 100}%`, height: '100%', background: RETAILER_COLORS[i % RETAILER_COLORS.length] }} />
          </div>
          <span className="num" style={{ fontSize: 12, fontWeight: 600, width: 14, textAlign: 'right' }}>
            {row.order_count}
          </span>
        </div>
      ))}
    </div>
  )
}

function CategoryView({ rows }: { rows: CategoryBreakdown[] }): React.JSX.Element {
  if (rows.length === 0) return <EmptyMini text="No categorized orders yet." />
  const max = Math.max(...rows.map((r) => r.unit_count), 1)
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-evenly' }}>
      {rows.map((row, i) => (
        <div key={row.category} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 11, color: 'var(--text-secondary)', width: 100, flexShrink: 0 }}>{row.category}</span>
          <div style={{ flex: 1, height: 22, background: 'oklch(15% 0.012 255 / 0.55)', borderRadius: 5, overflow: 'hidden' }}>
            <div style={{ width: `${(row.unit_count / max) * 100}%`, height: '100%', background: i % 2 === 0 ? 'var(--accent-cyan)' : 'var(--accent-violet)' }} />
          </div>
          <span className="num" style={{ fontSize: 12, fontWeight: 600, width: 20, textAlign: 'right' }}>
            {row.unit_count}
          </span>
        </div>
      ))}
    </div>
  )
}

function AttentionRow({ color, text }: { color: string; text: string }): React.JSX.Element {
  return (
    <div className="row" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 8px', margin: '0 -8px', borderRadius: 8 }}>
      <span style={{ width: 7, height: 7, borderRadius: '50%', background: color, flexShrink: 0 }} />
      <span style={{ fontSize: 12.5 }}>{text}</span>
    </div>
  )
}

function EmptyChart(): React.JSX.Element {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-faint)', fontSize: 13 }}>
      No orders yet — nothing to chart.
    </div>
  )
}

function EmptyMini({ text }: { text: string }): React.JSX.Element {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-faint)', fontSize: 12 }}>
      {text}
    </div>
  )
}

function DashboardLoading(): React.JSX.Element {
  return (
    <>
      <div className="screen-title">Dashboard</div>
      <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>Loading…</div>
    </>
  )
}

export default Dashboard
