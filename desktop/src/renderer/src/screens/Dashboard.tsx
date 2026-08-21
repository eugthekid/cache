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
import type { Screen } from '../components/NavRail'
import { Skel, TableSkeleton } from '../components/Skeleton'
import ErrorState from '../components/ErrorState'
import ImportWizard from '../components/ImportWizard'

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

function Dashboard({ onNavigate }: { onNavigate?: (screen: Screen) => void }): React.JSX.Element {
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
  const [showImport, setShowImport] = useState(false)

  useEffect(() => {
    load()
  }, [])

  async function load(): Promise<void> {
    setLoading(true)
    setError(null)
    try {
      const [s, m, a, r, c, orders] = await Promise.all([
        api.inventory.summary(),
        api.dashboard.monthly(6),
        api.dashboard.aging(),
        api.dashboard.byRetailer(),
        api.dashboard.byCategory(),
        api.orders.list({ status: 'failed', limit: 5 })
      ])
      setSummary(s)
      setMonthly(m)
      setAging(a)
      setByRetailer(r)
      setByCategory(c)
      setFailedOrders(orders)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard')
    } finally {
      setLoading(false)
    }
  }

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
  if (error) return <ErrorState screenTitle="Dashboard" message={error} onRetry={load} />

  const isFirstRun = (summary?.order_count ?? 0) === 0

  return (
    <>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div className="screen-title">Dashboard</div>
        <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)' }}>
          {new Date().toISOString().slice(0, 10)}
        </div>
      </div>

      <div
        style={{
          position: 'relative',
          display: 'grid',
          gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
          gap: 14,
          opacity: isFirstRun ? 0.42 : 1
        }}
      >
        <KpiCard label="Total spend" value={isFirstRun ? '—' : currency(summary?.total_cost_basis ?? 0)} sub={isFirstRun ? 'no orders yet' : `${summary?.order_count ?? 0} orders`} accent={!isFirstRun} />
        <KpiCard label="Est. inv. value" value={isFirstRun ? '—' : currency(summary?.est_inventory_value ?? 0)} sub={isFirstRun ? 'no units yet' : `${summary?.total_units ?? 0} units`} />
        <KpiCard label="In hand" value={isFirstRun ? '—' : String(summary?.in_hand ?? 0)} sub="units" />
        <KpiCard label="Listed" value={isFirstRun ? '—' : String(summary?.listed ?? 0)} sub="units" color={isFirstRun ? undefined : 'var(--status-warn)'} />
        <KpiCard label="Sold" value={isFirstRun ? '—' : String(summary?.sold ?? 0)} sub="all time" color={isFirstRun ? undefined : 'var(--status-success)'} />
      </div>

      {isFirstRun ? (
        <>
          <div className="card" style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '36px 40px' }}>
            <div style={{ width: '100%', maxWidth: 620, display: 'flex', flexDirection: 'column', gap: 22 }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, textAlign: 'center' }}>
                <div
                  style={{
                    width: 56,
                    height: 56,
                    borderRadius: 16,
                    background: 'linear-gradient(135deg, oklch(60% 0.1 215 / 0.28), oklch(55% 0.14 292 / 0.28))',
                    border: '1px solid var(--card-border)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    marginBottom: 2
                  }}
                >
                  <svg width="26" height="26" viewBox="0 0 20 20" fill="none">
                    <path d="M10 2 3 5.5 10 9l7-3.5L10 2Z" stroke="oklch(88% 0.08 250)" strokeWidth="1.4" strokeLinejoin="round" />
                    <path d="M3 5.5V14l7 3.5 7-3.5V5.5M10 9v8.5" stroke="oklch(88% 0.08 250)" strokeWidth="1.4" strokeLinejoin="round" />
                  </svg>
                </div>
                <div style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 700, letterSpacing: '-0.01em' }}>Nothing tracked yet</div>
                <div style={{ fontSize: 13.5, color: 'var(--text-secondary)', lineHeight: 1.55, maxWidth: 460 }}>
                  Pick any way to get your purchases in — you can use all three, and mix them however you like.
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <StartRow
                  iconBg="oklch(70% 0.06 265 / 0.18)"
                  icon={
                    <svg width="19" height="19" viewBox="0 0 20 20" fill="none">
                      <path d="M6 5.5c2.5-1 5.5-1 8 0M6 14.5c2.5 1 5.5 1 8 0M5 6.5C2.5 8.5 2.5 11.5 5 13.5M15 6.5c2.5 2 2.5 5 0 7" stroke="oklch(88% 0.05 265)" strokeWidth="1.5" strokeLinecap="round" />
                      <circle cx="7.5" cy="10" r="1.2" fill="oklch(88% 0.05 265)" />
                      <circle cx="12.5" cy="10" r="1.2" fill="oklch(88% 0.05 265)" />
                    </svg>
                  }
                  title="Connect your Discord bot"
                  body="Watches a channel and logs checkouts as they happen"
                  action="Connect"
                  primary
                  onClick={() => onNavigate?.('settings')}
                />
                <StartRow
                  iconBg="oklch(78% 0.17 150 / 0.16)"
                  icon={
                    <svg width="19" height="19" viewBox="0 0 20 20" fill="none">
                      <path d="M5 2h6l4 4v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z" stroke="oklch(85% 0.17 150)" strokeWidth="1.5" strokeLinejoin="round" />
                      <path d="M7.5 10l5 5M12.5 10l-5 5" stroke="oklch(85% 0.17 150)" strokeWidth="1.5" strokeLinecap="round" />
                    </svg>
                  }
                  title="Import a spreadsheet"
                  body="Bring in history you already track in .xlsx or .csv"
                  action="Choose file"
                  onClick={() => setShowImport(true)}
                />
                <StartRow
                  iconBg="oklch(80% 0.01 255 / 0.12)"
                  icon={
                    <svg width="19" height="19" viewBox="0 0 20 20" fill="none">
                      <path d="M10 4v12M4 10h12" stroke="oklch(90% 0.008 255)" strokeWidth="1.8" strokeLinecap="round" />
                    </svg>
                  }
                  title="Add an order by hand"
                  body="One-off purchases, or anything the bot missed"
                  action="New order"
                  onClick={() => onNavigate?.('orders')}
                />
              </div>
            </div>
          </div>
          {showImport && <ImportWizard onClose={() => setShowImport(false)} onImported={load} />}
        </>
      ) : (
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
      )}
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

function StartRow({
  icon,
  iconBg,
  title,
  body,
  action,
  primary,
  onClick
}: {
  icon: React.ReactNode
  iconBg: string
  title: string
  body: string
  action: string
  primary?: boolean
  onClick: () => void
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '16px 18px',
        borderRadius: 12,
        border: '1px solid var(--card-border)',
        background: 'oklch(90% 0.02 250 / 0.04)'
      }}
    >
      <div style={{ width: 38, height: 38, borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, background: iconBg }}>
        {icon}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600 }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 3 }}>{body}</div>
      </div>
      <button className={primary ? 'btn-primary' : 'btn-ghost'} style={{ padding: '9px 17px', fontSize: 12.5, flexShrink: 0 }} onClick={onClick}>
        {action}
      </button>
    </div>
  )
}

function DashboardLoading(): React.JSX.Element {
  return (
    <>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div className="screen-title">Dashboard</div>
        <Skel style={{ width: 74, height: 12 }} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 14 }}>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="card" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 9 }}>
            <Skel style={{ width: 62, height: 10 }} />
            <Skel style={{ width: 82, height: 20 }} />
            <Skel style={{ width: 50, height: 10 }} />
          </div>
        ))}
      </div>
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 16, minHeight: 0 }}>
        <div className="card" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Skel style={{ width: 130, height: 14 }} />
            <Skel style={{ width: 150, height: 24, borderRadius: 8 }} />
          </div>
          <Skel style={{ width: 160, height: 26 }} />
          <Skel style={{ flex: 1 }} />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 }}>
          <div className="card" style={{ padding: '18px 22px', flex: 1, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Skel style={{ width: 140, height: 14 }} />
            <TableSkeleton rows={4} widths={[3, 1]} />
          </div>
          <div className="card" style={{ padding: '18px 22px', flex: 0.85, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Skel style={{ width: 120, height: 14 }} />
            <TableSkeleton rows={2} widths={[1]} />
          </div>
        </div>
      </div>
    </>
  )
}

export default Dashboard
