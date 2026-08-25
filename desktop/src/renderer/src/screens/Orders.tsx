import { useEffect, useRef, useState } from 'react'
import { api, type Order, type OrderSort, type OrderStatus, type ShippingStatus } from '../api/client'
import GroupedOrders, { groupOrders, sortGroups } from '../components/GroupedOrders'
import StatusPill from '../components/StatusPill'
import ImportWizard from '../components/ImportWizard'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import BulkActionBar from '../components/BulkActionBar'
import { Skel, TableSkeleton } from '../components/Skeleton'
import type { Screen } from '../components/NavRail'

const ORDER_STATUSES: OrderStatus[] = ['success', 'failed', 'cancelled', 'pending']
const SHIPPING_STATUSES: ShippingStatus[] = ['not_shipped', 'label_created', 'in_transit', 'delivered', 'exception']

type PanelMode = 'closed' | 'new' | 'edit'

type DraftOrder = {
  raw_product_text: string
  site: string
  profile: string
  category: string
  unit_price: string
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
  unit_price: '',
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
    unit_price: order.unit_price != null ? String(order.unit_price) : '',
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

  const isNew = panelMode === 'new'
  const panelOpen = panelMode !== 'closed'

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
      const payload = {
        raw_product_text: draft.raw_product_text || null,
        site: draft.site || null,
        profile: draft.profile || null,
        category: draft.category || null,
        unit_price: draft.unit_price ? Number(draft.unit_price) : null,
        quantity: draft.quantity ? Number(draft.quantity) : null,
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
        selectOrder(created)
      } else {
        const updated = await api.orders.update(selectedId!, payload)
        setOrders((prev) => prev.map((o) => (o.id === updated.id ? updated : o)))
        selectOrder(updated)
      }
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
              style={{ flex: 1, minWidth: 170, height: 30, fontSize: 12 }}
            />

            <select
              className="field-input"
              value={sort}
              onChange={(e) => setSort(e.target.value as OrderSort)}
              style={{ width: 'auto', height: 30, fontSize: 12 }}
            >
              <option value="date_desc">Newest first</option>
              <option value="date_asc">Oldest first</option>
              <option value="price_desc">Price: high to low</option>
              <option value="price_asc">Price: low to high</option>
              <option value="product_asc">Product A–Z</option>
              <option value="retailer_asc">Retailer A–Z</option>
            </select>

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
                    <th style={{ paddingTop: 16 }}>Product</th>
                    <th style={{ paddingTop: 16 }}>Site</th>
                    <th style={{ paddingTop: 16 }}>Price</th>
                    <th style={{ paddingTop: 16 }}>Qty</th>
                    <th style={{ paddingTop: 16 }}>Status</th>
                    <th style={{ paddingTop: 16 }}>Shipping</th>
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
                  <th style={{ paddingTop: 16 }}>Product</th>
                  <th style={{ paddingTop: 16 }}>Order #</th>
                  <th style={{ paddingTop: 16 }}>Retailer</th>
                  <th style={{ paddingTop: 16 }}>Price</th>
                  <th style={{ paddingTop: 16 }}>Qty</th>
                  <th style={{ paddingTop: 16 }}>Status</th>
                  <th style={{ paddingTop: 16 }}>Shipping</th>
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
                    <td style={{ fontWeight: 500 }}>{order.raw_product_text ?? '—'}</td>
                    <td className="num" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                      {order.order_number || '—'}
                    </td>
                    <td style={{ color: 'var(--text-secondary)' }}>{order.retailer ?? order.site ?? '—'}</td>
                    <td className="num">{order.unit_price != null ? `$${order.unit_price.toFixed(2)}` : '—'}</td>
                    <td className="num">{order.quantity ?? '—'}</td>
                    <td>
                      <StatusPill status={order.status} />
                    </td>
                    <td>
                      {order.status === 'success' || order.status === 'pending' ? (
                        <StatusPill status={order.shipping_status} />
                      ) : (
                        <span style={{ color: 'var(--text-faint)' }}>—</span>
                      )}
                    </td>
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
              <Field label="Price">
                <input className="field-input num" type="number" step="0.01" value={draft.unit_price} onChange={(e) => updateDraft('unit_price', e.target.value)} />
              </Field>
              <Field label="Qty">
                <input className="field-input num" type="number" min="1" value={draft.quantity} onChange={(e) => updateDraft('quantity', e.target.value)} />
              </Field>
              <Field label="Date">
                <input className="field-input num" type="date" value={draft.purchased_at} onChange={(e) => updateDraft('purchased_at', e.target.value)} />
              </Field>
            </div>

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

            <div style={{ display: 'flex', gap: 10, marginTop: 4 }}>
              <button className="btn-primary" style={{ flex: 1 }} onClick={save} disabled={saving || !draft.raw_product_text}>
                {saving ? 'SAVING…' : 'SAVE CHANGES'}
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
