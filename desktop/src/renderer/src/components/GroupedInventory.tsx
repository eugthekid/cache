import { useState } from 'react'
import { api, type InventoryItem, type ProductGroup } from '../api/client'
import StatusPill from '../components/StatusPill'

interface GroupedInventoryProps {
  groups: ProductGroup[]
  items: InventoryItem[]
  /** Resolves a unit to its product, whether it carries product_id itself
   * (standalone/imported stock) or inherits it from its order. */
  productIdFor: (item: InventoryItem) => string | null
  onSelectItem: (item: InventoryItem) => void
  selectedId: string | null
  onChanged: () => void
}

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** Inventory rolled up to one row per product, expandable to the individual
 * units. This is the view that answers "how many of these do I have?"
 * without the user counting identical-looking rows by eye. */
function GroupedInventory({
  groups,
  items,
  productIdFor,
  onSelectItem,
  selectedId,
  onChanged
}: GroupedInventoryProps): React.JSX.Element {
  const [expanded, setExpanded] = useState<string | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draftName, setDraftName] = useState('')

  function toggle(key: string): void {
    setExpanded((prev) => (prev === key ? null : key))
  }

  async function saveName(productId: string): Promise<void> {
    const name = draftName.trim()
    setRenaming(null)
    if (!name) return
    await api.products.rename(productId, name)
    onChanged()
  }

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <th style={{ paddingTop: 16, width: 26 }} />
          <th style={{ paddingTop: 16, width: 40 }} />
          <th style={{ paddingTop: 16 }}>Product</th>
          <th style={{ paddingTop: 16 }}>Units</th>
          <th style={{ paddingTop: 16 }}>In hand</th>
          <th style={{ paddingTop: 16 }}>Sold</th>
          <th style={{ paddingTop: 16 }}>Cost basis</th>
        </tr>
      </thead>
      <tbody>
        {groups.map((group) => {
          const key = group.product_id ?? '__unmatched__'
          const isOpen = expanded === key
          const groupItems = isOpen
            ? items.filter((i) => (productIdFor(i) ?? '__unmatched__') === key)
            : []
          return [
            <tr
              key={key}
              className="row"
              onClick={() => toggle(key)}
              style={{ cursor: 'pointer', background: isOpen ? 'oklch(90% 0.02 250 / 0.06)' : undefined }}
            >
              <td style={{ color: 'var(--text-faint)', fontSize: 11 }}>{isOpen ? '▾' : '▸'}</td>
              <td>
                {group.image_url ? (
                  <img
                    src={group.image_url}
                    alt=""
                    style={{ width: 28, height: 28, objectFit: 'contain', borderRadius: 6, background: 'var(--field-bg)' }}
                  />
                ) : (
                  <div style={{ width: 28, height: 28, borderRadius: 6, background: 'var(--field-bg)' }} />
                )}
              </td>
              <td style={{ fontWeight: 500 }} onClick={(e) => isOpen && e.stopPropagation()}>
                {renaming === group.product_id ? (
                  <input
                    className="field-input"
                    autoFocus
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    onBlur={() => group.product_id && saveName(group.product_id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && group.product_id) saveName(group.product_id)
                      if (e.key === 'Escape') setRenaming(null)
                    }}
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <span
                    onDoubleClick={(e) => {
                      e.stopPropagation()
                      if (!group.product_id) return
                      setDraftName(group.name ?? '')
                      setRenaming(group.product_id)
                    }}
                    title={group.product_id ? 'Double-click to rename' : undefined}
                  >
                    {group.name}
                  </span>
                )}
                {group.awaiting_payment > 0 && (
                  <span className="pill pill-warn" style={{ marginLeft: 8 }}>
                    {group.awaiting_payment} unpaid
                  </span>
                )}
              </td>
              <td className="num" style={{ fontWeight: 600 }}>{group.total_units}</td>
              <td className="num" style={{ color: 'var(--text-secondary)' }}>{group.in_hand}</td>
              <td className="num" style={{ color: 'var(--text-secondary)' }}>{group.sold}</td>
              <td className="num">{money(group.total_cost_basis)}</td>
            </tr>,
            ...groupItems.map((item) => (
              <tr
                key={item.id}
                className="row"
                onClick={() => onSelectItem(item)}
                style={{
                  cursor: 'pointer',
                  background:
                    item.id === selectedId
                      ? 'linear-gradient(90deg, oklch(29% 0.06 215), oklch(27% 0.06 292 / 0.6))'
                      : 'oklch(15% 0.012 255 / 0.35)'
                }}
              >
                <td />
                <td />
                <td style={{ paddingLeft: 26, color: 'var(--text-secondary)', fontSize: 12 }}>
                  unit {item.unit_index ?? '—'}
                  {item.notes ? ` · ${item.notes}` : ''}
                </td>
                <td />
                <td colSpan={2}>
                  <StatusPill status={item.status} />
                  {item.status === 'sold' && item.money_received_at == null && (
                    <span className="pill pill-warn" style={{ marginLeft: 6 }}>
                      unpaid
                    </span>
                  )}
                </td>
                <td className="num" style={{ color: 'var(--text-secondary)' }}>
                  {item.cost_basis != null ? money(item.cost_basis) : '—'}
                </td>
              </tr>
            ))
          ]
        })}
      </tbody>
    </table>
  )
}

export default GroupedInventory
