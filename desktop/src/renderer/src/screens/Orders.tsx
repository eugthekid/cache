import { useEffect, useState } from 'react'
import { api, type Order, type OrderStatus, type ShippingStatus } from '../api/client'
import StatusPill from '../components/StatusPill'

const ORDER_STATUSES: OrderStatus[] = ['success', 'failed', 'cancelled', 'pending']
const SHIPPING_STATUSES: ShippingStatus[] = ['not_shipped', 'label_created', 'in_transit', 'delivered', 'exception']

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

function Orders(): React.JSX.Element {
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<DraftOrder>(BLANK_DRAFT)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const isNew = selectedId === null

  useEffect(() => {
    load()
  }, [])

  async function load(): Promise<void> {
    setLoading(true)
    try {
      const list = await api.orders.list({ limit: 200 })
      setOrders(list)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load orders')
    } finally {
      setLoading(false)
    }
  }

  function selectOrder(order: Order): void {
    setSelectedId(order.id)
    setDraft(orderToDraft(order))
    setSaveError(null)
  }

  function startNew(): void {
    setSelectedId(null)
    setDraft(BLANK_DRAFT)
    setSaveError(null)
  }

  function updateDraft<K extends keyof DraftOrder>(key: K, value: DraftOrder[K]): void {
    setDraft((prev) => ({ ...prev, [key]: value }))
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

  const showFailureReason = draft.status === 'failed' || draft.status === 'cancelled'
  const showShipping = draft.status === 'success' || draft.status === 'pending'

  if (loading) {
    return (
      <>
        <div className="screen-title">Orders</div>
        <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>Loading…</div>
      </>
    )
  }
  if (error) {
    return <div style={{ color: 'var(--status-failed)' }}>Couldn&rsquo;t load orders: {error}</div>
  }

  return (
    <>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div className="screen-title">Orders</div>
        <button className="btn-primary" onClick={startNew}>
          + NEW ORDER
        </button>
      </div>

      <div style={{ position: 'relative', flex: 1, display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16, minHeight: 0 }}>
        <div className="card" style={{ padding: '8px 16px 14px', overflow: 'auto' }}>
          {orders.length === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-faint)', fontSize: 13, flexDirection: 'column', gap: 6 }}>
              <div>No orders yet.</div>
              <div style={{ fontSize: 11.5 }}>Connect Discord, import a file, or add one by hand.</div>
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ paddingTop: 16 }}>Product</th>
                  <th style={{ paddingTop: 16 }}>Site</th>
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
                    <td style={{ fontWeight: 500 }}>{order.raw_product_text ?? '—'}</td>
                    <td style={{ color: 'var(--text-secondary)' }}>{order.site ?? '—'}</td>
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

        <div className="card" style={{ padding: '22px 24px', display: 'flex', flexDirection: 'column', gap: 14, overflow: 'auto' }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>{isNew ? 'New order' : 'Edit order'}</div>

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
            <button className="btn-ghost" style={{ flex: 1 }} onClick={startNew} disabled={saving}>
              CANCEL
            </button>
          </div>
        </div>
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
