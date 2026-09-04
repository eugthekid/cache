import { useEffect, useRef, useState } from 'react'
import { api, type Order, type OrderSort, type OrderStatus, type ShippingStatus } from '../api/client'
import GroupedOrders, { groupOrders, sortGroups } from '../components/GroupedOrders'
import ColumnPicker from '../components/ColumnPicker'
import StatusPill from '../components/StatusPill'
import ImportWizard from '../components/ImportWizard'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import BulkActionBar from '../components/BulkActionBar'
import { Skel, TableSkeleton } from '../components/Skeleton'
import type { Screen } from '../components/NavRail'

const ORDER_STATUSES: OrderStatus[] = ['success', 'failed', 'cancelled', 'pending']

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** The order total, from the per-unit price the API stores. */
function orderTotal(order: Order): number | null {
  return order.unit_price != null ? order.unit_price * (order.quantity ?? 1) : null
}

const FAINT = { color: 'var(--text-secondary)' } as const

/**
 * Every column the "All lines" table can show, in table order. Which ones
 * are actually rendered is the user's choice (persisted in localStorage --
 * see COLUMNS_KEY); DEFAULT_COLUMNS is what a fresh install shows.
 *
 * The row checkbox is deliberately NOT in here: it isn't data, it can't be
 * turned off without breaking bulk actions, and it always sits first.
 */
const COLUMNS: {
  key: string
  label: string
  render: (order: Order) => React.ReactNode
  cellClass?: string
  cellStyle?: React.CSSProperties
}[] = [
  { key: 'product', label: 'Product', render: (o) => o.product_name ?? o.raw_product_text ?? '—', cellStyle: { fontWeight: 500 } },
  { key: 'order_number', label: 'Order #', render: (o) => o.order_number || 'N/A', cellClass: 'num', cellStyle: { fontSize: 12, ...FAINT } },
  { key: 'retailer', label: 'Retailer', render: (o) => o.retailer ?? o.site ?? '—', cellStyle: FAINT },
  { key: 'profile', label: 'Profile', render: (o) => o.profile ?? '—', cellStyle: FAINT },
  { key: 'category', label: 'Category', render: (o) => o.category ?? '—', cellStyle: FAINT },
  { key: 'order_total', label: 'Order total', render: (o) => { const t = orderTotal(o); return t != null ? money(t) : '—' }, cellClass: 'num' },
  { key: 'unit_price', label: 'Unit price', render: (o) => (o.unit_price != null ? money(o.unit_price) : '—'), cellClass: 'num', cellStyle: FAINT },
  { key: 'quantity', label: 'Qty', render: (o) => o.quantity ?? '—', cellClass: 'num' },
  { key: 'purchased_at', label: 'Date', render: (o) => o.purchased_at?.slice(0, 10) ?? '—', cellClass: 'num', cellStyle: FAINT },
  { key: 'status', label: 'Status', render: (o) => <StatusPill status={o.status} /> },
  {
    key: 'shipping_status',
    label: 'Shipping',
    // Shipping only means something for an order that actually went
    // through -- a failed/cancelled one never ships, so showing
    // 'not_shipped' there would read as a pending delivery.
    render: (o) =>
      o.status === 'success' || o.status === 'pending' ? (
        <StatusPill status={o.shipping_status} />
      ) : (
        <span style={{ color: 'var(--text-faint)' }}>—</span>
      )
  },
  { key: 'carrier', label: 'Carrier', render: (o) => o.carrier_label ?? '—', cellStyle: FAINT },
  {
    key: 'tracking_number',
    label: 'Tracking #',
    // Links straight to the carrier's page when we know the carrier;
    // plain text otherwise, since there's nowhere meaningful to point.
    render: (o) =>
      o.tracking_number ? (
        o.tracking_url ? (
          <a
            href={o.tracking_url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            style={{ color: 'var(--accent-cyan)', textDecoration: 'none' }}
          >
            {o.tracking_number}
          </a>
        ) : (
          o.tracking_number
        )
      ) : (
        '—'
      ),
    cellClass: 'num',
    cellStyle: { fontSize: 12, ...FAINT }
  },
  {
    key: 'estimated_delivery',
    label: 'Est. delivery',
    // Stays "—" until a live tracking provider is configured; the column
    // exists now so the data has somewhere to land the moment one is.
    render: (o) => o.estimated_delivery?.slice(0, 10) ?? '—',
    cellClass: 'num',
    cellStyle: FAINT
  },
  { key: 'ship_to_label', label: 'Ship to', render: (o) => o.ship_to_label ?? '—', cellStyle: FAINT }
]

const DEFAULT_COLUMNS = [
  'product', 'order_number', 'retailer', 'profile', 'order_total', 'quantity', 'status', 'shipping_status'
]
const COLUMNS_KEY = 'cache_orders_columns'

function loadColumns(): Set<string> {
  try {
    const raw = localStorage.getItem(COLUMNS_KEY)
    if (!raw) return new Set(DEFAULT_COLUMNS)
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Set(DEFAULT_COLUMNS)
    // Drop anything that's no longer a real column, so a stored setting
    // from an older build can't leave a phantom header behind.
    const known = parsed.filter((k): k is string => typeof k === 'string' && COLUMNS.some((c) => c.key === k))
    return known.length ? new Set(known) : new Set(DEFAULT_COLUMNS)
  } catch {
    return new Set(DEFAULT_COLUMNS)
  }
}
const SHIPPING_STATUSES: ShippingStatus[] = ['not_shipped', 'label_created', 'in_transit', 'delivered', 'exception']

type PanelMode = 'closed' | 'new' | 'edit'

type DraftOrder = {
  raw_product_text: string
  site: string
  profile: string
  category: string
  /** What the whole order cost, NOT the per-unit price -- that's what a
   * receipt actually shows, so it's what you have to hand when typing one
   * in. The stored Order.unit_price stays per-unit (inventory cost_basis
   * and the dashboard's spend both depend on it being per-unit), so this
   * is divided by quantity on save and multiplied back on load. */
  order_total: string
  quantity: string
  purchased_at: string
  status: OrderStatus
  failure_reason: string
  order_number: string
  shipping_status: ShippingStatus
  tracking_number: string
  ship_to_label: string
  ship_to_address: string
}

const BLANK_DRAFT: DraftOrder = {
  raw_product_text: '',
  site: '',
  profile: '',
  category: '',
  order_total: '',
  quantity: '1',
  purchased_at: new Date().toISOString().slice(0, 10),
  status: 'success',
  failure_reason: '',
  order_number: '',
  shipping_status: 'not_shipped',
  tracking_number: '',
  ship_to_label: '',
  ship_to_address: ''
}

function orderToDraft(order: Order): DraftOrder {
  return {
    raw_product_text: order.raw_product_text ?? '',
    site: order.site ?? '',
    profile: order.profile ?? '',
    category: order.category ?? '',
    // Back out the order total from the stored per-unit price. toFixed(2)
    // then Number() drops the float-multiplication noise (3 x 19.99 =
    // 59.269999999999996) that would otherwise land in the input box.
    order_total:
      order.unit_price != null
        ? String(Number((order.unit_price * (order.quantity ?? 1)).toFixed(2)))
        : '',
    quantity: order.quantity != null ? String(order.quantity) : '1',
    purchased_at: order.purchased_at ? order.purchased_at.slice(0, 10) : '',
    status: order.status,
    failure_reason: order.failure_reason ?? '',
    order_number: order.order_number ?? '',
    shipping_status: order.shipping_status,
    tracking_number: order.tracking_number ?? '',
    ship_to_label: order.ship_to_label ?? '',
    ship_to_address: order.ship_to_address ?? ''
  }
}

/** The one Source every manually-added order belongs to -- created once,
 * on first use, and reused after (mirrors bot/src/api_client.py's
 * get-or-create pattern for Discord channels, just with no per-channel
 * scoping since there's only ever one "manual entry" source). */
async function getOrCreateManualSource(): Promise<string> {
  const sources = await api.sources.list()
  const existing = sources.find((s) => s.type === 'manual')
  if (existing) return existing.id
  const created = await api.sources.create('manual', 'Manual entry')
  return created.id
}

function Orders({ onNavigate }: { onNavigate?: (screen: Screen) => void }): React.JSX.Element {
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [panelMode, setPanelMode] = useState<PanelMode>('closed')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<DraftOrder>(BLANK_DRAFT)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())

  const [view, setView] = useState<'grouped' | 'lines'>(
    () => (localStorage.getItem('cache_orders_view') as 'grouped' | 'lines') || 'grouped'
  )
  const [statusFilter, setStatusFilter] = useState<Set<OrderStatus>>(new Set())
  const [sort, setSort] = useState<OrderSort>('date_desc')
  const [search, setSearch] = useState('')
  // Guards against out-of-order responses: changing two filters quickly
  // fires two requests, and without this the SLOWER (older) one can land
  // last and repaint the table with results the user already moved past.
  const requestSeq = useRef(0)
  const [savedNotice, setSavedNotice] = useState(false)
  const [visibleColumns, setVisibleColumns] = useState<Set<string>>(loadColumns)
  const [alerts, setAlerts] = useState<Order[]>([])

  async function loadAlerts(): Promise<void> {
    try {
      setAlerts(await api.orders.shippingAlerts())
    } catch {
      // A failed alert fetch must never take the Orders screen down with
      // it -- the orders themselves are the point, this is a garnish.
      setAlerts([])
    }
  }

  useEffect(() => {
    loadAlerts()
  }, [])

  async function dismissAlerts(): Promise<void> {
    await api.orders.ackShippingAlerts()
    setAlerts([])
  }

  function changeColumns(next: Set<string>): void {
    // Never let the table become headerless -- an empty selection leaves
    // nothing but checkboxes and no way to tell the rows apart.
    if (next.size === 0) return
    setVisibleColumns(next)
    localStorage.setItem(COLUMNS_KEY, JSON.stringify([...next]))
  }

  function resetColumns(): void {
    setVisibleColumns(new Set(DEFAULT_COLUMNS))
    localStorage.removeItem(COLUMNS_KEY)
  }

  // Driven by COLUMNS' own order, not selection order, so toggling a
  // column back on returns it to its original place in the table.
  const activeColumns = COLUMNS.filter((c) => visibleColumns.has(c.key))
  // Cleared on unmount so the close-the-panel callback can't fire against
  // a screen that's already gone.
  const savedTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(savedTimer.current), [])

  const isNew = panelMode === 'new'
  const panelOpen = panelMode !== 'closed'

  // What one unit cost, derived from the total the user typed. Shown as a
  // read-only hint so the split is visible before saving -- it's the value
  // that actually gets stored, and it becomes each inventory unit's cost
  // basis. Null (rather than 0) whenever it can't be computed, so the hint
  // hides instead of claiming a free unit.
  const perUnitPrice = ((): number | null => {
    const total = draft.order_total ? Number(draft.order_total) : null
    const qty = draft.quantity ? Number(draft.quantity) : null
    if (total == null || Number.isNaN(total)) return null
    if (qty == null || Number.isNaN(qty) || qty <= 0) return null
    return total / qty
  })()

  // Filtering and sorting run server-side so they apply to ALL orders, not
  // just whichever page the client happens to be holding.
  useEffect(() => {
    load()
  }, [statusFilter, sort, search])

  function changeView(next: 'grouped' | 'lines'): void {
    setView(next)
    localStorage.setItem('cache_orders_view', next)
    setCheckedIds(new Set())
  }

  function toggleStatus(status: OrderStatus): void {
    setStatusFilter((prev) => {
      const next = new Set(prev)
      if (next.has(status)) next.delete(status)
      else next.add(status)
      return next
    })
  }

  async function load(): Promise<void> {
    const seq = ++requestSeq.current
    setLoading(true)
    setError(null)
    try {
      const list = await api.orders.list({
        status: statusFilter.size ? Array.from(statusFilter).join(',') : undefined,
        search: search.trim() || undefined,
        sort
      })
      if (seq !== requestSeq.current) return // a newer request already won
      setOrders(list)
    } catch (err) {
      if (seq !== requestSeq.current) return
      setError(err instanceof Error ? err.message : 'Failed to load orders')
    } finally {
      if (seq === requestSeq.current) setLoading(false)
    }
  }

  function selectOrder(order: Order): void {
    setSelectedId(order.id)
    setDraft(orderToDraft(order))
    setSaveError(null)
    setPanelMode('edit')
  }

  function startNew(): void {
    setSelectedId(null)
    setDraft(BLANK_DRAFT)
    setSaveError(null)
    setPanelMode('new')
  }

  function closePanel(): void {
    setPanelMode('closed')
    setSelectedId(null)
  }

  function updateDraft<K extends keyof DraftOrder>(key: K, value: DraftOrder[K]): void {
    setDraft((prev) => ({ ...prev, [key]: value }))
  }

  function toggleChecked(id: string): void {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAllChecked(): void {
    setCheckedIds((prev) => (prev.size === orders.length ? new Set() : new Set(orders.map((o) => o.id))))
  }

  async function save(): Promise<void> {
    setSaving(true)
    setSaveError(null)
    try {
      // The form collects the ORDER TOTAL; the API stores a per-unit price
      // (see DraftOrder.order_total). Guard the divide on qty > 0 rather
      // than just truthiness so a stray "0" can't produce Infinity.
      const qty = draft.quantity ? Number(draft.quantity) : null
      const total = draft.order_total ? Number(draft.order_total) : null
      const payload = {
        raw_product_text: draft.raw_product_text || null,
        site: draft.site || null,
        profile: draft.profile || null,
        category: draft.category || null,
        unit_price: total != null && qty != null && qty > 0 ? total / qty : total,
        quantity: qty,
        purchased_at: draft.purchased_at ? new Date(draft.purchased_at).toISOString() : null,
        status: draft.status,
        failure_reason: draft.failure_reason || null,
        order_number: draft.order_number || null,
        shipping_status: draft.shipping_status,
        tracking_number: draft.tracking_number || null,
        ship_to_label: draft.ship_to_label || null,
        ship_to_address: draft.ship_to_address || null
      }

      if (isNew) {
        const sourceId = await getOrCreateManualSource()
        const created = await api.orders.create({
          ...payload,
          source_id: sourceId,
          external_id: `manual:${crypto.randomUUID()}`
        })
        setOrders((prev) => [created, ...prev])
      } else {
        const updated = await api.orders.update(selectedId!, payload)
        setOrders((prev) => prev.map((o) => (o.id === updated.id ? updated : o)))
      }
      // Confirm, then close: the save is invisible otherwise -- the panel
      // just sat there looking unchanged, with no way to tell a successful
      // save from a no-op. Held briefly so the confirmation is actually
      // readable before the panel goes away.
      // A save can be what flips an order to delivered/exception, so the
      // alert feed has to re-read rather than wait for the next mount.
      loadAlerts()
      setSavedNotice(true)
      savedTimer.current = window.setTimeout(() => {
        setSavedNotice(false)
        closePanel()
      }, 900)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  async function deleteCurrent(): Promise<void> {
    if (!selectedId) return
    if (!window.confirm('Delete this order? Any inventory it created goes too. A Discord resync won’t bring it back — use Rebuild in Settings if you want it again.')) return
    setDeleting(true)
    try {
      await api.orders.delete(selectedId)
      setOrders((prev) => prev.filter((o) => o.id !== selectedId))
      setCheckedIds((prev) => {
        const next = new Set(prev)
        next.delete(selectedId)
        return next
      })
      closePanel()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to delete')
    } finally {
      setDeleting(false)
    }
  }

  async function bulkSetStatus(status: OrderStatus): Promise<void> {
    const ids = Array.from(checkedIds)
    await api.orders.bulkSetStatus(ids, status)
    setOrders((prev) => prev.map((o) => (checkedIds.has(o.id) ? { ...o, status } : o)))
    setCheckedIds(new Set())
  }

  async function bulkDelete(): Promise<void> {
    const ids = Array.from(checkedIds)
    await api.orders.bulkDelete(ids)
    setOrders((prev) => prev.filter((o) => !checkedIds.has(o.id)))
    if (selectedId && checkedIds.has(selectedId)) closePanel()
    setCheckedIds(new Set())
  }

  const showFailureReason = draft.status === 'failed' || draft.status === 'cancelled'
  const showShipping = draft.status === 'success' || draft.status === 'pending'

  if (loading) {
    return (
      <>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div className="screen-title">Orders</div>
          <Skel style={{ width: 190, height: 34, borderRadius: 9 }} />
        </div>
        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16, minHeight: 0 }}>
          <div className="card" style={{ padding: '8px 16px 14px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', gap: 14, padding: '16px 0 10px' }}>
              {[2.4, 1.2, 0.7, 0.5, 0.8, 0.9].map((w, i) => (
                <Skel key={i} style={{ flex: w, height: 10 }} />
              ))}
            </div>
            <div style={{ borderTop: '1px solid var(--divider)' }} />
            <TableSkeleton rows={7} widths={[2.4, 1.2, 0.7, 0.5, 0.8, 0.9]} />
          </div>
          <div className="card" style={{ padding: '22px 24px', display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Skel style={{ width: 90, height: 14 }} />
            {Array.from({ length: 5 }).map((_, i) => (
              <Skel key={i} style={{ height: 38, borderRadius: 8 }} />
            ))}
          </div>
        </div>
      </>
    )
  }
  if (error) {
    return <ErrorState screenTitle="Orders" message={error} onRetry={load} />
  }

  return (
    <>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div className="screen-title">Orders</div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn-ghost" onClick={() => setShowImport(true)}>
            IMPORT
          </button>
          <button className="btn-primary" onClick={startNew}>
            + NEW ORDER
          </button>
        </div>
      </div>

      {showImport && <ImportWizard onClose={() => setShowImport(false)} onImported={load} />}

      {alerts.length > 0 && (
        <div
          className="card"
          style={{
            padding: '11px 15px', display: 'flex', alignItems: 'center', gap: 12,
            borderLeft: '3px solid var(--status-warn)'
          }}
        >
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 3 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>
              {alerts.length} shipping update{alerts.length === 1 ? '' : 's'}
            </div>
            <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
              {alerts
                .slice(0, 3)
                .map((a) => `${a.product_name ?? a.raw_product_text ?? 'Order'} — ${a.shipping_status}`)
                .join(' · ')}
              {alerts.length > 3 && ` · +${alerts.length - 3} more`}
            </div>
          </div>
          <button className="link-action" onClick={dismissAlerts} style={{ fontSize: 11.5 }}>
            Dismiss
          </button>
        </div>
      )}

      {checkedIds.size > 0 && (
        <BulkActionBar
          count={checkedIds.size}
          statusOptions={ORDER_STATUSES}
          onSetStatus={bulkSetStatus}
          onDelete={bulkDelete}
          onClear={() => setCheckedIds(new Set())}
          noun="order"
        />
      )}

      <div
        style={
          panelOpen
            ? { position: 'relative', flex: 1, display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16, minHeight: 0 }
            : { position: 'relative', flex: 1, minHeight: 0 }
        }
      >
        <div className="card" style={{ padding: '8px 16px 14px', overflow: 'auto', display: 'flex', flexDirection: 'column', height: '100%' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '10px 0 8px' }}>
            <div style={{ display: 'flex', gap: 3, background: 'var(--field-bg)', border: '1px solid var(--field-border)', borderRadius: 8, padding: 3 }}>
              {(['grouped', 'lines'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => changeView(m)}
                  style={{
                    padding: '5px 11px', borderRadius: 6, fontSize: 11.5, fontWeight: 600,
                    border: 'none', cursor: 'pointer',
                    background: view === m ? 'var(--accent-gradient)' : 'transparent',
                    color: view === m ? 'oklch(14% 0.01 255)' : 'var(--text-secondary)'
                  }}
                >
                  {m === 'grouped' ? 'By order' : 'All lines'}
                </button>
              ))}
            </div>

            {ORDER_STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => toggleStatus(s)}
                className={`pill ${statusFilter.has(s) ? `pill-${s === 'success' ? 'success' : s === 'failed' ? 'failed' : 'neutral'}` : 'pill-neutral'}`}
                style={{
                  cursor: 'pointer', border: 'none',
                  opacity: statusFilter.size === 0 || statusFilter.has(s) ? 1 : 0.4
                }}
              >
                <span className="dot" />
                {s}
              </button>
            ))}

            <input
              className="field-input"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search product, order number, retailer…"
              style={{ flex: 1, minWidth: 170, height: 30, padding: '0 12px', fontSize: 12 }}
            />

            <select
              className="field-input"
              value={sort}
              onChange={(e) => setSort(e.target.value as OrderSort)}
              style={{ width: 'auto', height: 30, padding: '0 12px', fontSize: 12 }}
            >
              <option value="date_desc">Newest first</option>
              <option value="date_asc">Oldest first</option>
              <option value="price_desc">Price: high to low</option>
              <option value="price_asc">Price: low to high</option>
              <option value="product_asc">Product A–Z</option>
              <option value="retailer_asc">Retailer A–Z</option>
            </select>

            {/* Only the flat table is column-driven -- the grouped view has
                its own fixed cart-level layout (see GroupedOrders.tsx). */}
            {view === 'lines' && (
              <ColumnPicker
                options={COLUMNS.map(({ key, label }) => ({ key, label }))}
                visible={visibleColumns}
                onChange={changeColumns}
                onReset={resetColumns}
              />
            )}

            <span className="num" style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
              {view === 'grouped'
                ? `${groupOrders(orders).length} orders`
                : `${orders.length} lines`}
            </span>
          </div>

          {orders.length === 0 ? (
            <>
              <table style={{ width: '100%', borderCollapse: 'collapse', opacity: 0.4 }}>
                <thead>
                  <tr>
                    <th style={{ paddingTop: 16, width: 32 }} />
                    {activeColumns.map((col) => (
                      <th key={col.key} style={{ paddingTop: 16 }}>
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
              </table>
              <div style={{ borderTop: '1px solid var(--divider)' }} />
              <EmptyState
                icon={
                  <svg width="24" height="24" viewBox="0 0 20 20" fill="none">
                    <path d="M5 3h7l3 3v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" stroke="oklch(80% 0.012 255)" strokeWidth="1.4" strokeLinejoin="round" />
                    <path d="M7 9h6M7 12h6M7 15h4" stroke="oklch(80% 0.012 255)" strokeWidth="1.4" strokeLinecap="round" />
                  </svg>
                }
                iconBg="oklch(90% 0.02 250 / 0.07)"
                title="No orders yet"
                body="Once your Discord bot is connected, checkouts land here automatically — successes and failures both."
                actions={
                  <>
                    <button className="btn-primary" style={{ padding: '9px 17px', fontSize: 12.5 }} onClick={() => onNavigate?.('settings')}>
                      Connect Discord
                    </button>
                    <button className="btn-ghost" style={{ padding: '9px 17px', fontSize: 12.5 }} onClick={() => setShowImport(true)}>
                      Import a file
                    </button>
                    <button className="btn-ghost" style={{ padding: '9px 17px', fontSize: 12.5 }} onClick={startNew}>
                      Add manually
                    </button>
                  </>
                }
              />
            </>
          ) : view === 'grouped' ? (
            <GroupedOrders groups={sortGroups(groupOrders(orders), sort)} selectedId={selectedId} onSelect={selectOrder} />
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ paddingTop: 16, width: 32 }}>
                    <input type="checkbox" checked={checkedIds.size === orders.length} onChange={toggleAllChecked} />
                  </th>
                  {activeColumns.map((col) => (
                    <th key={col.key} style={{ paddingTop: 16 }}>
                      {col.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <tr
                    key={order.id}
                    className="row"
                    onClick={() => selectOrder(order)}
                    style={{
                      cursor: 'pointer',
                      background: order.id === selectedId ? 'linear-gradient(90deg, oklch(29% 0.06 215), oklch(27% 0.06 292 / 0.6))' : undefined
                    }}
                  >
                    <td onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={checkedIds.has(order.id)} onChange={() => toggleChecked(order.id)} />
                    </td>
                    {activeColumns.map((col) => (
                      <td key={col.key} className={col.cellClass} style={col.cellStyle}>
                        {col.render(order)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {panelOpen && (
          <div className="card" style={{ padding: '22px 24px', display: 'flex', flexDirection: 'column', gap: 14, overflow: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>{isNew ? 'New order' : 'Edit order'}</div>
              <button className="link-action" onClick={closePanel} aria-label="Close">
                Close
              </button>
            </div>

            <Field label="Product">
              <input className="field-input" value={draft.raw_product_text} onChange={(e) => updateDraft('raw_product_text', e.target.value)} />
            </Field>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="Site">
                <input className="field-input" value={draft.site} onChange={(e) => updateDraft('site', e.target.value)} />
              </Field>
              <Field label="Profile">
                <input className="field-input" value={draft.profile} onChange={(e) => updateDraft('profile', e.target.value)} />
              </Field>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="Category">
                <input className="field-input" value={draft.category} onChange={(e) => updateDraft('category', e.target.value)} placeholder="e.g. Sneakers" />
              </Field>
              <Field label="Order number">
                <input className="field-input" value={draft.order_number} onChange={(e) => updateDraft('order_number', e.target.value)} />
              </Field>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
              <Field label="Order total">
                <input className="field-input num" type="number" step="0.01" value={draft.order_total} onChange={(e) => updateDraft('order_total', e.target.value)} />
              </Field>
              <Field label="Qty">
                <input className="field-input num" type="number" min="1" value={draft.quantity} onChange={(e) => updateDraft('quantity', e.target.value)} />
              </Field>
              <Field label="Date">
                <input className="field-input num" type="date" value={draft.purchased_at} onChange={(e) => updateDraft('purchased_at', e.target.value)} />
              </Field>
            </div>

            {perUnitPrice != null && (
              <div className="num" style={{ fontSize: 11.5, color: 'var(--text-faint)', marginTop: -6 }}>
                {money(perUnitPrice)} per unit
              </div>
            )}

            <Field label="Order status">
              <select className="select" value={draft.status} onChange={(e) => updateDraft('status', e.target.value as OrderStatus)}>
                {ORDER_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>

            {showFailureReason && (
              <Field label="Failure reason">
                <input className="field-input" value={draft.failure_reason} onChange={(e) => updateDraft('failure_reason', e.target.value)} />
              </Field>
            )}

            {showShipping && (
              <div style={{ borderTop: '1px solid var(--divider)', paddingTop: 13, display: 'flex', flexDirection: 'column', gap: 13 }}>
                <Field label="Shipping status">
                  <select className="select" value={draft.shipping_status} onChange={(e) => updateDraft('shipping_status', e.target.value as ShippingStatus)}>
                    {SHIPPING_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Tracking number">
                  <input className="field-input num" value={draft.tracking_number} onChange={(e) => updateDraft('tracking_number', e.target.value)} />
                </Field>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 12 }}>
                  <Field label="Ship-to label">
                    <input className="field-input" value={draft.ship_to_label} onChange={(e) => updateDraft('ship_to_label', e.target.value)} placeholder="Home" />
                  </Field>
                  <Field label="Ship-to address">
                    <input className="field-input" value={draft.ship_to_address} onChange={(e) => updateDraft('ship_to_address', e.target.value)} />
                  </Field>
                </div>
              </div>
            )}

            {saveError && <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{saveError}</div>}

            {savedNotice && (
              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '9px 13px', borderRadius: 8,
                  background: 'var(--status-success-bg)', color: 'var(--status-success)',
                  fontSize: 12.5, fontWeight: 600
                }}
              >
                ✓ Changes saved
              </div>
            )}

            <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
              <button className="btn-primary" style={{ flex: 1 }} onClick={save} disabled={saving || savedNotice || !draft.raw_product_text}>
                {saving ? 'SAVING…' : savedNotice ? 'SAVED ✓' : 'SAVE CHANGES'}
              </button>
              <button className="btn-ghost" style={{ flex: 1 }} onClick={closePanel} disabled={saving}>
                CANCEL
              </button>
            </div>
            {!isNew && (
              <button className="btn-danger" onClick={deleteCurrent} disabled={saving || deleting}>
                {deleting ? 'DELETING…' : 'DELETE ORDER'}
              </button>
            )}
          </div>
        )}
      </div>
    </>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div className="field-label">{label}</div>
      {children}
    </div>
  )
}

export default Orders
