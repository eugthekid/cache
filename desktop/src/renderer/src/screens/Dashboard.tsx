import { useEffect, useRef, useState } from 'react'
import {
  api,
  type BreakdownRow,
  type DashboardOverview,
  type InventorySummary,
  type OverviewPeriod
} from '../api/client'
import type { Screen } from '../components/NavRail'
import { Skel, TableSkeleton } from '../components/Skeleton'
import ErrorState from '../components/ErrorState'
import ImportWizard from '../components/ImportWizard'
import OverviewChart, { type ChartMetric } from '../components/OverviewChart'
import { retailerColor } from '../components/retailerBrand'

type BreakdownTab = 'category' | 'channel' | 'product'

const PERIODS: { key: OverviewPeriod; label: string; profitLabel: string; spentNote: string; noun: string }[] = [
  { key: 'weekly', label: 'Weekly', profitLabel: 'Profit · this week so far', spentNote: 'ordered this week', noun: 'this week' },
  { key: 'monthly', label: 'Monthly', profitLabel: 'Profit · this month so far', spentNote: 'ordered this month', noun: 'this month' },
  { key: 'all', label: 'All time', profitLabel: 'Total profit · all time', spentNote: 'ordered, all time', noun: 'all time' }
]

const STAGE_STYLE: Record<string, { label: string; color: string }> = {
  in_hand: { label: 'In hand', color: 'var(--status-success)' },
  in_transit: { label: 'In transit', color: 'var(--accent-cyan)' },
  not_shipped: { label: 'Order placed', color: 'var(--text-faint)' }
}

function usd(n: number): string {
  return `${n < 0 ? '-' : ''}$${Math.abs(Math.round(n)).toLocaleString()}`
}

function signedUsd(n: number): string {
  return `${n < 0 ? '-' : '+'}${usd(Math.abs(n))}`
}

function pct(fraction: number): string {
  return `${Math.round(fraction * 100)}%`
}

function Segmented<T extends string>({
  options,
  value,
  onChange
}: {
  options: { key: T; label: string }[]
  value: T
  onChange: (next: T) => void
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        gap: 3,
        background: 'var(--field-bg)',
        border: '1px solid var(--field-border)',
        borderRadius: 8,
        padding: 3
      }}
    >
      {options.map((o) => (
        <button
          key={o.key}
          onClick={() => onChange(o.key)}
          style={{
            padding: '5px 11px',
            borderRadius: 6,
            fontSize: 11.5,
            fontWeight: 600,
            border: 'none',
            cursor: 'pointer',
            background: value === o.key ? 'var(--accent-gradient)' : 'transparent',
            color: value === o.key ? 'oklch(14% 0.01 255)' : 'var(--text-secondary)'
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Tile({
  label,
  value,
  sub,
  color,
  hero
}: {
  label: string
  value: string
  sub?: string
  color?: string
  hero?: boolean
}): React.JSX.Element {
  return (
    <div className="card" style={{ padding: '16px 18px' }}>
      <div className="field-label">{label}</div>
      <div className="num" style={{ fontSize: hero ? 32 : 22, fontWeight: 500, marginTop: 6, color }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 5 }}>{sub}</div>}
    </div>
  )
}

function Dashboard({ onNavigate }: { onNavigate?: (screen: Screen) => void }): React.JSX.Element {
  const [summary, setSummary] = useState<InventorySummary | null>(null)
  const [overview, setOverview] = useState<DashboardOverview | null>(null)
  const [period, setPeriod] = useState<OverviewPeriod>('all')
  const [metric, setMetric] = useState<ChartMetric>('spent-revenue')
  const [tab, setTab] = useState<BreakdownTab>('category')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showImport, setShowImport] = useState(false)
  const requestId = useRef(0)

  // The first load shows the skeleton; changing the period just swaps the
  // numbers in place, so the screen (and the buttons you're clicking) never
  // unmount underneath you.
  async function fetchOverview(next: OverviewPeriod): Promise<void> {
    const id = ++requestId.current
    try {
      const [s, o] = await Promise.all([api.inventory.summary(), api.dashboard.overview(next)])
      if (id !== requestId.current) return
      setError(null)
      setSummary(s)
      setOverview(o)
    } catch (err) {
      if (id !== requestId.current) return
      setError(err instanceof Error ? err.message : 'Failed to load dashboard')
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }

  function reload(): void {
    setLoading(true)
    fetchOverview(period)
  }

  function changePeriod(next: OverviewPeriod): void {
    setPeriod(next)
    fetchOverview(next)
  }

  // The screen starts out in its loading state, so the first fetch doesn't
  // need to switch it on again.
  useEffect(() => {
    // Fetching on mount is the point of this effect; the state updates happen
    // after the request returns, not during the render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchOverview('all')
  }, [])

  if (loading) return <DashboardLoading />
  if (error) return <ErrorState screenTitle="Dashboard" message={error} onRetry={reload} />

  const isFirstRun = (summary?.order_count ?? 0) === 0
  const meta = PERIODS.find((p) => p.key === period)!

  return (
    <>
      <div className="screen-header">
        <div className="screen-title">Dashboard</div>
        {!isFirstRun && <Segmented options={PERIODS} value={period} onChange={changePeriod} />}
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
          {showImport && <ImportWizard onClose={() => setShowImport(false)} onImported={reload} />}
        </>
      ) : overview ? (
        <div style={{ position: 'relative', flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 14, paddingBottom: 6 }}>
          <Kpis overview={overview} meta={meta} />
          <ChartCard overview={overview} metric={metric} onMetric={setMetric} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 14 }}>
            <BreakdownCard overview={overview} tab={tab} onTab={setTab} />
            <InventoryCard overview={overview} />
          </div>
        </div>
      ) : null}
    </>
  )
}

function Kpis({
  overview,
  meta
}: {
  overview: DashboardOverview
  meta: (typeof PERIODS)[number]
}): React.JSX.Element {
  const k = overview.kpis
  const parts = [`${k.units_sold} unit${k.units_sold === 1 ? '' : 's'} sold`]
  if (k.roi != null) parts.push(`ROI ${k.roi >= 0 ? '+' : '-'}${pct(Math.abs(k.roi))}`)
  if (k.margin != null) parts.push(`margin ${pct(k.margin)}`)
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) repeat(3, minmax(0, 1fr))', gap: 14 }}>
      <Tile
        hero
        label={meta.profitLabel}
        value={signedUsd(k.profit)}
        color={k.profit >= 0 ? 'var(--status-success)' : 'var(--status-failed)'}
        sub={parts.join(' · ')}
      />
      <Tile label="Revenue" value={usd(k.revenue)} sub={`${k.units_sold} unit${k.units_sold === 1 ? '' : 's'} sold`} />
      <Tile label="Spent" value={usd(k.spent)} sub={meta.spentNote} />
      <Tile label="Unsold inventory" value={usd(overview.inventory.cost)} sub={`${overview.inventory.units} units, at cost`} />
    </div>
  )
}

function ChartCard({
  overview,
  metric,
  onMetric
}: {
  overview: DashboardOverview
  metric: ChartMetric
  onMetric: (m: ChartMetric) => void
}): React.JSX.Element {
  const unit = overview.chart.granularity === 'week' ? 'week' : 'month'
  const swatch = (color: string): React.JSX.Element => (
    <span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, marginRight: 6, background: color }} />
  )
  return (
    <div className="card" style={{ padding: '18px 22px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 13.5, fontWeight: 600 }}>
          {metric === 'profit' ? `Profit by ${unit}` : `Spent vs. revenue by ${unit}`}
        </div>
        <Segmented
          options={[
            { key: 'spent-revenue' as ChartMetric, label: 'Spent vs. revenue' },
            { key: 'profit' as ChartMetric, label: 'Profit' }
          ]}
          value={metric}
          onChange={onMetric}
        />
      </div>
      <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--text-secondary)', margin: '10px 0 6px', flexWrap: 'wrap' }}>
        {metric === 'profit' ? (
          <span>{swatch('var(--status-success)')}Profit (sale price minus average cost)</span>
        ) : (
          <>
            <span>{swatch('var(--accent-cyan)')}Spent (purchases)</span>
            <span>{swatch('var(--status-success)')}Revenue (sales)</span>
          </>
        )}
      </div>
      <OverviewChart buckets={overview.chart.buckets} metric={metric} />
      <div style={{ fontSize: 11.5, color: 'var(--text-faint)', marginTop: 4 }}>
        * This {unit} is still in progress. Spent counts purchases by the day they were ordered; revenue and profit count
        units by the day you sold them.
      </div>
    </div>
  )
}

const TABS: { key: BreakdownTab; label: string }[] = [
  { key: 'category', label: 'Category' },
  { key: 'channel', label: 'Sales channel' },
  { key: 'product', label: 'Product' }
]

function BreakdownCard({
  overview,
  tab,
  onTab
}: {
  overview: DashboardOverview
  tab: BreakdownTab
  onTab: (t: BreakdownTab) => void
}): React.JSX.Element {
  const rows: BreakdownRow[] = overview.breakdown[tab]
  const max = Math.max(1, ...rows.map((r) => r.profit))
  const cols = 'minmax(150px, 2.4fr) minmax(50px, 1fr) 84px 44px 52px'
  return (
    <div className="card" style={{ padding: '18px 22px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <div style={{ fontSize: 13.5, fontWeight: 600 }}>Profit breakdown</div>
        <Segmented options={TABS} value={tab} onChange={onTab} />
      </div>
      {rows.length === 0 ? (
        <div style={{ fontSize: 12.5, color: 'var(--text-faint)', padding: '14px 0' }}>No sales in this period yet.</div>
      ) : (
        <>
          <div className="field-label" style={{ display: 'grid', gridTemplateColumns: cols, gap: 10, paddingBottom: 6 }}>
            <span>{TABS.find((t) => t.key === tab)?.label}</span>
            <span />
            <span style={{ textAlign: 'right' }}>Profit</span>
            <span style={{ textAlign: 'right' }}>Units</span>
            <span style={{ textAlign: 'right' }}>ROI</span>
          </div>
          {rows.map((r) => (
            <div
              key={r.name}
              style={{
                display: 'grid',
                gridTemplateColumns: cols,
                gap: 10,
                alignItems: 'center',
                padding: '8px 0',
                borderTop: '1px solid var(--divider)',
                fontSize: 12.5
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.name}>
                {tab === 'product' ? r.name.replace(/^Pokémon (TCG|Trading Card Game): /, '') : r.name}
              </span>
              <div style={{ height: 8, background: 'var(--field-bg)', borderRadius: 4, overflow: 'hidden' }}>
                <div
                  style={{
                    height: '100%',
                    width: `${Math.max(0, (r.profit / max) * 100)}%`,
                    background: r.profit < 0 ? 'var(--status-failed)' : 'var(--status-success)',
                    borderRadius: 4
                  }}
                />
              </div>
              <span className="num" style={{ textAlign: 'right', color: r.profit < 0 ? 'var(--status-failed)' : 'var(--status-success)' }}>
                {signedUsd(r.profit)}
              </span>
              <span className="num" style={{ textAlign: 'right' }}>{r.units}</span>
              <span className="num" style={{ textAlign: 'right' }}>{r.cost > 0 ? pct(r.profit / r.cost) : '—'}</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

function InventoryCard({ overview }: { overview: DashboardOverview }): React.JSX.Element {
  const inv = overview.inventory
  const spend = overview.spend_by_retailer
  const shown = spend.slice(0, 4)
  const rest = spend.slice(4).reduce((t, r) => t + r.spent, 0)
  const lines = rest > 0 ? [...shown, { name: 'All other retailers', spent: rest }] : shown
  const maxSpend = Math.max(1, ...lines.map((l) => l.spent))
  return (
    <div className="card" style={{ padding: '18px 22px' }}>
      <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 10 }}>Inventory and spending</div>
      <div className="field-label">Unsold units, at cost</div>
      <div className="num" style={{ fontSize: 24, fontWeight: 500, marginTop: 4 }}>{usd(inv.cost)}</div>
      <div style={{ display: 'flex', height: 12, borderRadius: 6, overflow: 'hidden', background: 'var(--field-bg)', margin: '10px 0 8px' }}>
        {inv.stages.map((s) => (
          <div key={s.stage} style={{ width: `${inv.cost > 0 ? (s.cost / inv.cost) * 100 : 0}%`, background: STAGE_STYLE[s.stage]?.color }} />
        ))}
      </div>
      {inv.stages.map((s) => (
        <div key={s.stage} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, padding: '5px 0' }}>
          <span>
            <span style={{ color: STAGE_STYLE[s.stage]?.color }}>&#9632;</span> {STAGE_STYLE[s.stage]?.label} · {s.units} units
          </span>
          <span className="num">{usd(s.cost)}</span>
        </div>
      ))}
      <div className="field-label" style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--divider)' }}>
        Spent by retailer · all time
      </div>
      {lines.map((l) => {
        const color = retailerColor(l.name) ?? 'var(--text-secondary)'
        return (
          <div key={l.name} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '5px 0', fontSize: 12.5 }}>
            <span style={{ minWidth: 150, color }}>{l.name}</span>
            <div style={{ flex: 1, height: 8, background: 'var(--field-bg)', borderRadius: 4, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${(l.spent / maxSpend) * 100}%`, background: color, borderRadius: 4 }} />
            </div>
            <span className="num">{usd(l.spent)}</span>
          </div>
        )
      })}
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
      <div className="screen-header">
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
