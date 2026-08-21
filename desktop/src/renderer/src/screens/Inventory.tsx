import { useEffect, useState } from 'react'
import { api, type InventoryItem, type InventoryStatus, type Order } from '../api/client'
import StatusPill from '../components/StatusPill'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import { Skel, TableSkeleton } from '../components/Skeleton'
import ImportWizard from '../components/ImportWizard'
import type { Screen } from '../components/NavRail'

const ITEM_STATUSES: InventoryStatus[] = ['in_hand', 'listed', 'sold', 'returned', 'lost']

type DraftItem = {
  status: InventoryStatus
  cost_basis: string
  listed_price: string
  listed_platform: string
  sold_price: string
  sold_platform: string
  sold_at: string
  notes: string
}

function itemToDraft(item: InventoryItem): DraftItem {
  return {
    status: item.status,
    cost_basis: item.cost_basis != null ? String(item.cost_basis) : '',
    listed_price: item.listed_price != null ? String(item.listed_price) : '',
    listed_platform: item.listed_platform ?? '',
    sold_price: item.sold_price != null ? String(item.sold_price) : '',
    sold_platform: item.sold_platform ?? '',
    sold_at: item.sold_at ? item.sold_at.slice(0, 10) : '',
    notes: item.notes ?? ''
  }
}

/** An item linked to an order has no product name of its own -- it comes
 * from the order (see docs/DATA-MODEL.md on why product_text only matters
 * when order_id is NULL). Resolving that here, once, means every other
 * piece of this screen can just ask "what is this called" without caring
 * which of the two cases it's in. */
function productName(item: InventoryItem, ordersById: Map<string, Order>): string {
  if (item.product_text) return item.product_text
  const order = item.order_id ? ordersById.get(item.order_id) : undefined
  return order?.raw_product_text ?? 'Unknown item'
}

function fromOrderLabel(item: InventoryItem, ordersById: Map<string, Order>): string {
  if (!item.order_id) return '—'
  const order = ordersById.get(item.order_id)
  if (!order?.purchased_at) return '—'
  return order.purchased_at.slice(0, 10)
}

function Inventory({ onNavigate }: { onNavigate?: (screen: Screen) => void }): React.JSX.Element {
  const [items, setItems] = useState<InventoryItem[]>([])
  const [ordersById, setOrdersById] = useState<Map<string, Order>>(new Map())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<DraftItem | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [showImport, setShowImport] = useState(false)

  useEffect(() => {
    load()
  }, [])

  async function load(): Promise<void> {
    setLoading(true)
    setError(null)
    try {
      const [itemList, orderList] = await Promise.all([api.inventory.list(), api.orders.list({ limit: 200 })])
      setItems(itemList)
      setOrdersById(new Map(orderList.map((o) => [o.id, o])))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load inventory')
    } finally {
      setLoading(false)
    }
  }

  function selectItem(item: InventoryItem): void {
    setSelectedId(item.id)
    setDraft(itemToDraft(item))
    setSaveError(null)
  }

  function updateDraft<K extends keyof DraftItem>(key: K, value: DraftItem[K]): void {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  async function save(): Promise<void> {
    if (!selectedId || !draft) return
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await api.inventory.update(selectedId, {
        status: draft.status,
        cost_basis: draft.cost_basis ? Number(draft.cost_basis) : null,
        listed_price: draft.listed_price ? Number(draft.listed_price) : null,
        listed_platform: draft.listed_platform || null,
        sold_price: draft.sold_price ? Number(draft.sold_price) : null,
        sold_platform: draft.sold_platform || null,
        sold_at: draft.sold_at ? new Date(draft.sold_at).toISOString() : undefined,
        notes: draft.notes || null
      })
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)))
      selectItem(updated)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  const selectedItem = items.find((i) => i.id === selectedId) ?? null
  const profit =
    selectedItem?.status === 'sold' && selectedItem.sold_price != null && selectedItem.cost_basis != null
      ? selectedItem.sold_price - selectedItem.cost_basis
      : null

  if (loading) {
    return (
      <>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div className="screen-title">Inventory</div>
          <Skel style={{ width: 60, height: 12 }} />
        </div>
        <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16, minHeight: 0 }}>
          <div className="card" style={{ padding: '8px 16px 14px', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', gap: 14, padding: '16px 0 10px' }}>
              {[2, 1.2, 1, 0.8, 1].map((w, i) => (
                <Skel key={i} style={{ flex: w, height: 10 }} />
              ))}
            </div>
            <div style={{ borderTop: '1px solid var(--divider)' }} />
            <TableSkeleton rows={7} widths={[2, 1.2, 1, 0.8, 1]} />
          </div>
          <div className="card" style={{ padding: '22px 24px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Skel style={{ width: 160, height: 14 }} />
          </div>
        </div>
      </>
    )
  }
  if (error) {
    return <ErrorState screenTitle="Inventory" message={error} onRetry={load} />
  }

  return (
    <>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div className="screen-title">Inventory</div>
        <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)' }}>
          {items.length} unit{items.length === 1 ? '' : 's'}
        </div>
      </div>

      <div style={{ position: 'relative', flex: 1, display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16, minHeight: 0 }}>
        <div className="card" style={{ padding: '8px 16px 14px', overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          {items.length === 0 ? (
            <>
              <table style={{ width: '100%', borderCollapse: 'collapse', opacity: 0.4 }}>
                <thead>
                  <tr>
                    <th style={{ paddingTop: 16 }}>Product</th>
                    <th style={{ paddingTop: 16 }}>From order</th>
                    <th style={{ paddingTop: 16 }}>Cost basis</th>
                    <th style={{ paddingTop: 16 }}>Status</th>
                    <th style={{ paddingTop: 16 }}>Sale</th>
                  </tr>
                </thead>
              </table>
              <div style={{ borderTop: '1px solid var(--divider)' }} />
              <EmptyState
                icon={
                  <svg width="24" height="24" viewBox="0 0 20 20" fill="none">
                    <path d="M10 2 3 5.5 10 9l7-3.5L10 2Z" stroke="oklch(88% 0.08 250)" strokeWidth="1.4" strokeLinejoin="round" />
                    <path d="M3 5.5V14l7 3.5 7-3.5V5.5M10 9v8.5" stroke="oklch(88% 0.08 250)" strokeWidth="1.4" strokeLinejoin="round" />
                  </svg>
                }
                iconBg="oklch(60% 0.1 215 / 0.2)"
                title="Nothing in hand yet"
                body="It fills in once a successful order arrives or you import stock you already hold."
                actions={
                  <>
                    <button className="btn-primary" style={{ padding: '9px 17px', fontSize: 12.5 }} onClick={() => onNavigate?.('orders')}>
                      View orders
                    </button>
                    <button className="btn-ghost" style={{ padding: '9px 17px', fontSize: 12.5 }} onClick={() => setShowImport(true)}>
                      Import a file
                    </button>
                  </>
                }
              />
            </>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ paddingTop: 16 }}>Product</th>
                  <th style={{ paddingTop: 16 }}>From order</th>
                  <th style={{ paddingTop: 16 }}>Cost basis</th>
                  <th style={{ paddingTop: 16 }}>Status</th>
                  <th style={{ paddingTop: 16 }}>Sale</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const saleText =
                    item.status === 'sold' && item.sold_price != null
                      ? `$${item.sold_price.toFixed(2)} ${item.sold_platform ?? ''}`
                      : item.status === 'listed' && item.listed_price != null
                        ? `$${item.listed_price.toFixed(2)} ${item.listed_platform ?? ''}`
                        : '—'
                  return (
                    <tr
                      key={item.id}
                      className="row"
                      onClick={() => selectItem(item)}
                      style={{
                        cursor: 'pointer',
                        background: item.id === selectedId ? 'linear-gradient(90deg, oklch(29% 0.06 215), oklch(27% 0.06 292 / 0.6))' : undefined
                      }}
                    >
                      <td style={{ fontWeight: 500 }}>{productName(item, ordersById)}</td>
                      <td className="num" style={{ color: 'var(--text-secondary)' }}>
                        {fromOrderLabel(item, ordersById)}
                      </td>
                      <td className="num">{item.cost_basis != null ? `$${item.cost_basis.toFixed(2)}` : '—'}</td>
                      <td>
                        <StatusPill status={item.status} />
                      </td>
                      <td className="num" style={{ color: 'var(--text-secondary)' }}>
                        {saleText}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="card" style={{ padding: '22px 24px', display: 'flex', flexDirection: 'column', gap: 14, overflow: 'auto' }}>
          {!selectedItem || !draft ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-faint)', fontSize: 13 }}>
              Select a unit to see details.
            </div>
          ) : (
            <>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>Unit detail</div>
              <div>
                <div style={{ fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 600 }}>
                  {productName(selectedItem, ordersById)}
                </div>
                <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 4 }}>
                  {selectedItem.order_id ? `from order ${fromOrderLabel(selectedItem, ordersById)}` : 'no linked order (imported)'}
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <Field label="Cost basis">
                  <input className="field-input num" type="number" step="0.01" value={draft.cost_basis} onChange={(e) => updateDraft('cost_basis', e.target.value)} />
                </Field>
                <Field label="Status">
                  <select className="select" value={draft.status} onChange={(e) => updateDraft('status', e.target.value as InventoryStatus)}>
                    {ITEM_STATUSES.map((s) => (
                      <option key={s} value={s}>
                        {s.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>

              {draft.status === 'listed' && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <Field label="Listed price">
                    <input className="field-input num" type="number" step="0.01" value={draft.listed_price} onChange={(e) => updateDraft('listed_price', e.target.value)} />
                  </Field>
                  <Field label="Platform">
                    <input className="field-input" value={draft.listed_platform} onChange={(e) => updateDraft('listed_platform', e.target.value)} placeholder="eBay" />
                  </Field>
                </div>
              )}

              {draft.status === 'sold' && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                    <Field label="Sold price">
                      <input className="field-input num" type="number" step="0.01" value={draft.sold_price} onChange={(e) => updateDraft('sold_price', e.target.value)} />
                    </Field>
                    <Field label="Platform">
                      <input className="field-input" value={draft.sold_platform} onChange={(e) => updateDraft('sold_platform', e.target.value)} placeholder="StockX" />
                    </Field>
                  </div>
                  <Field label="Sold date">
                    <input className="field-input num" type="date" value={draft.sold_at} onChange={(e) => updateDraft('sold_at', e.target.value)} />
                  </Field>
                  {profit != null && (
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '13px 16px',
                        borderRadius: 10,
                        background: `linear-gradient(135deg, ${profit >= 0 ? 'oklch(29% 0.08 150)' : 'oklch(29% 0.08 25)'}, ${profit >= 0 ? 'oklch(26% 0.06 150)' : 'oklch(26% 0.06 25)'})`
                      }}
                    >
                      <div className="field-label" style={{ color: profit >= 0 ? 'var(--status-success)' : 'var(--status-failed)' }}>
                        Profit
                      </div>
                      <div className="num" style={{ fontSize: 18, fontWeight: 700, color: profit >= 0 ? 'var(--status-success)' : 'var(--status-failed)' }}>
                        {profit >= 0 ? '+' : ''}${profit.toFixed(2)}
                      </div>
                    </div>
                  )}
                </>
              )}

              <Field label="Notes">
                <input className="field-input" value={draft.notes} onChange={(e) => updateDraft('notes', e.target.value)} />
              </Field>

              {saveError && <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{saveError}</div>}

              <div style={{ display: 'flex', gap: 10, marginTop: 'auto' }}>
                <button className="btn-primary" style={{ flex: 1 }} onClick={save} disabled={saving}>
                  {saving ? 'SAVING…' : 'SAVE CHANGES'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {showImport && <ImportWizard onClose={() => setShowImport(false)} onImported={load} />}
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

export default Inventory
