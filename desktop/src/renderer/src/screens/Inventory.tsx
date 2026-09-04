import { useEffect, useState } from 'react'
import { api, type InventoryItem, type InventoryStatus, type Order } from '../api/client'
import StatusPill from '../components/StatusPill'
import EmptyState from '../components/EmptyState'
import ErrorState from '../components/ErrorState'
import BulkActionBar from '../components/BulkActionBar'
import { Skel, TableSkeleton } from '../components/Skeleton'
import ImportWizard from '../components/ImportWizard'
import AddInventoryItem from '../components/AddInventoryItem'
import GroupedInventory from '../components/GroupedInventory'
import ProductDetail from '../components/ProductDetail'
import type { ProductGroup } from '../api/client'
import type { Screen } from '../components/NavRail'

type ViewMode = 'units' | 'grouped'

const ITEM_STATUSES: InventoryStatus[] = ['in_hand', 'listed', 'sold', 'returned', 'lost']

type InventorySort = 'units_desc' | 'name_asc' | 'name_desc' | 'value_desc' | 'value_asc'

const UNCATEGORIZED = '__uncategorized__'

function compareGroups(a: ProductGroup, b: ProductGroup, sort: InventorySort): number {
  switch (sort) {
    case 'name_asc':
      return (a.name ?? '').localeCompare(b.name ?? '')
    case 'name_desc':
      return (b.name ?? '').localeCompare(a.name ?? '')
    case 'value_desc':
      return b.total_cost_basis - a.total_cost_basis
    case 'value_asc':
      return a.total_cost_basis - b.total_cost_basis
    default:
      // Matches the backend's own default ordering (see products.py's
      // grouped_inventory) so picking this option never visibly reorders
      // anything the user didn't ask to reorder.
      return b.total_units - a.total_units || (a.name ?? '').localeCompare(b.name ?? '')
  }
}

type DraftItem = {
  status: InventoryStatus
  cost_basis: string
  location: string
  listed_price: string
  listed_platform: string
  sold_price: string
  sold_platform: string
  sold_at: string
  money_received: boolean
  notes: string
}

function itemToDraft(item: InventoryItem): DraftItem {
  return {
    status: item.status,
    cost_basis: item.cost_basis != null ? String(item.cost_basis) : '',
    location: item.location ?? '',
    listed_price: item.listed_price != null ? String(item.listed_price) : '',
    listed_platform: item.listed_platform ?? '',
    sold_price: item.sold_price != null ? String(item.sold_price) : '',
    sold_platform: item.sold_platform ?? '',
    sold_at: item.sold_at ? item.sold_at.slice(0, 10) : '',
    money_received: item.money_received_at != null,
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
  return order?.product_name ?? order?.raw_product_text ?? 'Unknown item'
}

/** Same sort options as compareGroups, applied per-unit instead of per-
 * product -- "most units first" doesn't mean anything for a single unit,
 * so that option just leaves the flat view in whatever order it loaded. */
function compareItems(
  a: InventoryItem,
  b: InventoryItem,
  sort: InventorySort,
  ordersById: Map<string, Order>
): number {
  switch (sort) {
    case 'name_asc':
      return productName(a, ordersById).localeCompare(productName(b, ordersById))
    case 'name_desc':
      return productName(b, ordersById).localeCompare(productName(a, ordersById))
    case 'value_desc':
      return (b.cost_basis ?? 0) - (a.cost_basis ?? 0)
    case 'value_asc':
      return (a.cost_basis ?? 0) - (b.cost_basis ?? 0)
    default:
      return 0
  }
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
  const [deleting, setDeleting] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [showAddItem, setShowAddItem] = useState(false)
  const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set())
  const [view, setView] = useState<ViewMode>(
    () => (localStorage.getItem('cache_inventory_view') as ViewMode) || 'grouped'
  )
  const [groups, setGroups] = useState<ProductGroup[]>([])
  const [viewingProductKey, setViewingProductKey] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [sort, setSort] = useState<InventorySort>('units_desc')

  function changeView(next: ViewMode): void {
    setView(next)
    localStorage.setItem('cache_inventory_view', next)
    // Checkboxes only exist in the flat view; leaving a stale selection
    // behind would show a bulk bar with no way to clear it.
    setCheckedIds(new Set())
    setViewingProductKey(null)
  }

  /** A unit's product comes from itself when standalone, otherwise from its
   * order -- mirrors the backend's rule so both views agree. */
  function productIdFor(item: InventoryItem): string | null {
    if (item.product_id) return item.product_id
    const order = item.order_id ? ordersById.get(item.order_id) : undefined
    return order?.product_id ?? null
  }

  /** Identifies a product-group for click-through/filtering, same as the
   * backend's grouped_inventory: a real product_id when there is one,
   * otherwise the normalized name -- NOT a shared '__unmatched__' bucket,
   * which would make clicking into any one unmatched product show every
   * other unmatched product's units mixed in with it. */
  function groupKey(productId: string | null, name: string | null): string {
    return productId ?? (name ?? 'unmatched').trim().toLowerCase()
  }

  // Categories come from whatever's actually in the data, not a hardcoded
  // list -- "Pokemon"/"Sneakers"/etc. are free text the catalog matcher or
  // the user assigns, not a fixed enum, so a new one just shows up here.
  const categoryOptions = Array.from(
    new Set(groups.map((g) => g.category).filter((c): c is string => !!c))
  ).sort((a, b) => a.localeCompare(b))
  const hasUncategorized = groups.some((g) => !g.category && g.total_units > 0)

  const searchLower = search.trim().toLowerCase()
  function matchesFilters(name: string, category: string | null): boolean {
    if (searchLower && !name.toLowerCase().includes(searchLower)) return false
    if (categoryFilter === 'all') return true
    if (categoryFilter === UNCATEGORIZED) return !category
    return category === categoryFilter
  }

  const visibleGroups = groups
    .filter((g) => matchesFilters(g.name ?? '', g.category))
    .sort((a, b) => compareGroups(a, b, sort))

  // Units don't carry their own category -- look it up via the product
  // they belong to, same as the grouped view does server-side.
  const categoryByProductId = new Map(groups.map((g) => [g.product_id ?? '__unmatched__', g.category]))
  const visibleItems = items
    .filter((item) => matchesFilters(productName(item, ordersById), categoryByProductId.get(productIdFor(item) ?? '__unmatched__') ?? null))
    .sort((a, b) => compareItems(a, b, sort, ordersById))

  const filtersActive = search.trim() !== '' || categoryFilter !== 'all'

  useEffect(() => {
    load()
  }, [])

  async function load(): Promise<void> {
    setLoading(true)
    setError(null)
    try {
      const [itemList, orderList, groupList] = await Promise.all([
        api.inventory.list(),
        api.orders.list({ limit: 500 }),
        api.products.grouped()
      ])
      setItems(itemList)
      setOrdersById(new Map(orderList.map((o) => [o.id, o])))
      setGroups(groupList)
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

  function closePanel(): void {
    setSelectedId(null)
    setDraft(null)
  }

  function updateDraft<K extends keyof DraftItem>(key: K, value: DraftItem[K]): void {
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev))
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
    setCheckedIds((prev) => (prev.size === visibleItems.length ? new Set() : new Set(visibleItems.map((i) => i.id))))
  }

  async function save(): Promise<void> {
    if (!selectedId || !draft) return
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await api.inventory.update(selectedId, {
        status: draft.status,
        cost_basis: draft.cost_basis ? Number(draft.cost_basis) : null,
        location: draft.location || null,
        listed_price: draft.listed_price ? Number(draft.listed_price) : null,
        listed_platform: draft.listed_platform || null,
        sold_price: draft.sold_price ? Number(draft.sold_price) : null,
        sold_platform: draft.sold_platform || null,
        sold_at: draft.sold_at ? new Date(draft.sold_at).toISOString() : undefined,
        money_received: draft.money_received,
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

  async function deleteCurrent(): Promise<void> {
    if (!selectedId) return
    if (!window.confirm('Delete this inventory unit? It will be hidden everywhere, and a Discord resync won’t bring it back.')) return
    setDeleting(true)
    try {
      await api.inventory.delete(selectedId)
      setItems((prev) => prev.filter((i) => i.id !== selectedId))
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

  async function bulkSetStatus(status: InventoryStatus): Promise<void> {
    const ids = Array.from(checkedIds)
    await api.inventory.bulkSetStatus(ids, status)
    setItems((prev) => prev.map((i) => (checkedIds.has(i.id) ? { ...i, status } : i)))
    setCheckedIds(new Set())
  }

  async function bulkDelete(): Promise<void> {
    const ids = Array.from(checkedIds)
    await api.inventory.bulkDelete(ids)
    setItems((prev) => prev.filter((i) => !checkedIds.has(i.id)))
    if (selectedId && checkedIds.has(selectedId)) closePanel()
    setCheckedIds(new Set())
  }

  const selectedItem = items.find((i) => i.id === selectedId) ?? null
  const panelOpen = selectedItem !== null && draft !== null
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
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div className="screen-title">Inventory</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)' }}>
            {filtersActive ? `${visibleItems.length} of ${items.length}` : items.length} unit
            {items.length === 1 ? '' : 's'}
            {view === 'grouped' && groups.length > 0 &&
              ` · ${filtersActive ? `${visibleGroups.length} of ${groups.length}` : groups.length} products`}
          </div>
          <div style={{ display: 'flex', gap: 4, background: 'var(--field-bg)', border: '1px solid var(--field-border)', borderRadius: 8, padding: 3 }}>
            {(['grouped', 'units'] as ViewMode[]).map((m) => (
              <button
                key={m}
                onClick={() => changeView(m)}
                style={{
                  padding: '5px 12px',
                  borderRadius: 6,
                  fontSize: 11.5,
                  fontWeight: 600,
                  border: 'none',
                  cursor: 'pointer',
                  background: view === m ? 'var(--accent-gradient)' : 'transparent',
                  color: view === m ? 'oklch(14% 0.01 255)' : 'var(--text-secondary)'
                }}
              >
                {m === 'grouped' ? 'By product' : 'All units'}
              </button>
            ))}
          </div>
          <button className="btn-ghost" onClick={() => setShowImport(true)}>
            IMPORT
          </button>
          <button className="btn-primary" onClick={() => setShowAddItem(true)}>
            + ADD ITEM
          </button>
        </div>
      </div>

      {checkedIds.size > 0 && (
        <BulkActionBar
          count={checkedIds.size}
          statusOptions={ITEM_STATUSES}
          onSetStatus={bulkSetStatus}
          onDelete={bulkDelete}
          onClear={() => setCheckedIds(new Set())}
          noun="unit"
        />
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <input
          className="field-input"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search products…"
          style={{ flex: 1, minWidth: 170, height: 30, padding: '0 12px', fontSize: 12 }}
        />

        <select
          className="field-input"
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          style={{ width: 'auto', height: 30, padding: '0 12px', fontSize: 12 }}
        >
          <option value="all">All categories</option>
          {categoryOptions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
          {hasUncategorized && <option value={UNCATEGORIZED}>Uncategorized</option>}
        </select>

        <select
          className="field-input"
          value={sort}
          onChange={(e) => setSort(e.target.value as InventorySort)}
          style={{ width: 'auto', height: 30, padding: '0 12px', fontSize: 12 }}
        >
          <option value="units_desc">Most units first</option>
          <option value="name_asc">Name A–Z</option>
          <option value="name_desc">Name Z–A</option>
          <option value="value_desc">Value: high to low</option>
          <option value="value_asc">Value: low to high</option>
        </select>
      </div>

      <div
        style={
          panelOpen
            ? { position: 'relative', flex: 1, display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 16, minHeight: 0 }
            : { position: 'relative', flex: 1, minHeight: 0 }
        }
      >
        <div className="card" style={{ padding: '8px 16px 14px', overflow: 'auto', display: 'flex', flexDirection: 'column', height: '100%' }}>
          {items.length === 0 ? (
            <>
              <table style={{ width: '100%', borderCollapse: 'collapse', opacity: 0.4 }}>
                <thead>
                  <tr>
                    <th style={{ paddingTop: 16, width: 32 }} />
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
          ) : view === 'grouped' && viewingProductKey ? (
            <ProductDetail
              group={
                groups.find((g) => groupKey(g.product_id, g.name) === viewingProductKey) ?? {
                  product_id: null,
                  name: 'Unmatched',
                  total_units: 0,
                  in_hand: 0,
                  listed: 0,
                  sold: 0,
                  total_cost_basis: 0,
                  total_sold_revenue: 0,
                  awaiting_payment: 0,
                  avg_sale_price: null,
                  total_profit: null,
                  image_url: null,
                  category: null
                }
              }
              units={items.filter((i) => groupKey(productIdFor(i), productName(i, ordersById)) === viewingProductKey)}
              ordersById={ordersById}
              onBack={() => setViewingProductKey(null)}
              onSelectUnit={selectItem}
              selectedId={selectedId}
            />
          ) : view === 'grouped' && visibleGroups.length === 0 ? (
            <EmptyState
              icon={<span style={{ fontSize: 18 }}>🔍</span>}
              iconBg="oklch(60% 0.1 215 / 0.2)"
              title="No matches"
              body="Nothing in your inventory matches this search and filter combination."
            />
          ) : view === 'grouped' ? (
            <GroupedInventory
              groups={visibleGroups}
              onOpenProduct={(group) => setViewingProductKey(groupKey(group.product_id, group.name))}
              onChanged={load}
            />
          ) : visibleItems.length === 0 ? (
            <EmptyState
              icon={<span style={{ fontSize: 18 }}>🔍</span>}
              iconBg="oklch(60% 0.1 215 / 0.2)"
              title="No matches"
              body="Nothing in your inventory matches this search and filter combination."
            />
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ paddingTop: 16, width: 32 }}>
                    <input type="checkbox" checked={checkedIds.size === visibleItems.length} onChange={toggleAllChecked} />
                  </th>
                  <th style={{ paddingTop: 16 }}>Product</th>
                  <th style={{ paddingTop: 16 }}>From order</th>
                  <th style={{ paddingTop: 16 }}>Cost basis</th>
                  <th style={{ paddingTop: 16 }}>Status</th>
                  <th style={{ paddingTop: 16 }}>Sale</th>
                </tr>
              </thead>
              <tbody>
                {visibleItems.map((item) => {
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
                      <td onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={checkedIds.has(item.id)} onChange={() => toggleChecked(item.id)} />
                      </td>
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

        {panelOpen && selectedItem && draft && (
          <div className="card" style={{ padding: '22px 24px', display: 'flex', flexDirection: 'column', gap: 14, overflow: 'auto' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: 13.5, fontWeight: 600 }}>Unit detail</div>
              <button className="link-action" onClick={closePanel} aria-label="Close">
                Close
              </button>
            </div>
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

            <Field label="Location">
              <input className="field-input" value={draft.location} onChange={(e) => updateDraft('location', e.target.value)} placeholder="Closet A, Storage bin 3…" />
            </Field>

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
                <label style={{ display: 'flex', alignItems: 'center', gap: 9, cursor: 'pointer', padding: '2px 0' }}>
                  <input type="checkbox" checked={draft.money_received} onChange={(e) => updateDraft('money_received', e.target.checked)} />
                  <span style={{ fontSize: 12.5 }}>Money received</span>
                  {selectedItem.money_received_at && (
                    <span className="num" style={{ fontSize: 11, color: 'var(--text-faint)', marginLeft: 'auto' }}>
                      {selectedItem.money_received_at.slice(0, 10)}
                    </span>
                  )}
                </label>
                {!draft.money_received && (
                  <div className="num" style={{ fontSize: 11, color: 'var(--status-warn)' }}>
                    Sold — payment not received yet
                  </div>
                )}
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
            <button className="btn-danger" onClick={deleteCurrent} disabled={saving || deleting}>
              {deleting ? 'DELETING…' : 'DELETE UNIT'}
            </button>
          </div>
        )}
      </div>

      {showImport && <ImportWizard onClose={() => setShowImport(false)} onImported={load} />}
      {showAddItem && <AddInventoryItem onClose={() => setShowAddItem(false)} onAdded={load} />}
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
