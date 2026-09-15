import { useState } from 'react'
import { api, type ProductGroup } from '../api/client'

interface GroupedInventoryProps {
  groups: ProductGroup[]
  /** Opens the full per-unit detail screen for this product -- see
   * ProductDetail.tsx. Units aren't shown inline here any more: a product
   * can hold 90+ units, and listing them all in this table was both
   * unreadable and (per user feedback) not the right shape for what a
   * unit actually needs to show (order #, location, sale price...). */
  onOpenProduct: (group: ProductGroup) => void
  onChanged: () => void
  /** Mass-select for bulk delete/edit/duplicate -- keyed by the same
   * groupKey() scheme Inventory.tsx uses everywhere else a product needs
   * an identity beyond its (possibly absent) product_id. */
  checkedKeys: Set<string>
  onToggle: (group: ProductGroup) => void
  onToggleAll: () => void
}

function money(n: number): string {
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** Inventory rolled up to one row per product. Click a row to drill into
 * its individual units on their own screen. */
function GroupedInventory({
  groups,
  onOpenProduct,
  onChanged,
  checkedKeys,
  onToggle,
  onToggleAll
}: GroupedInventoryProps): React.JSX.Element {
  // undefined, not null: a group with no product_id (a standalone item with
  // no linked Product) has group.product_id === null, and `renaming ===
  // group.product_id` would read as "currently renaming" for every such
  // row on first render if this started out null too.
  const [renaming, setRenaming] = useState<string | undefined>(undefined)
  const [draftName, setDraftName] = useState('')

  async function saveName(productId: string): Promise<void> {
    const name = draftName.trim()
    setRenaming(undefined)
    if (!name) return
    await api.products.rename(productId, name)
    onChanged()
  }

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <th style={{ paddingTop: 16, width: 32 }}>
            <input type="checkbox" checked={groups.length > 0 && checkedKeys.size === groups.length} onChange={onToggleAll} />
          </th>
          <th style={{ paddingTop: 16, width: 40 }} />
          <th style={{ paddingTop: 16 }}>Product</th>
          <th style={{ paddingTop: 16 }}>Units</th>
          <th style={{ paddingTop: 16 }}>In hand</th>
          <th style={{ paddingTop: 16 }}>Sold</th>
          <th style={{ paddingTop: 16 }}>Avg. sale price</th>
          <th style={{ paddingTop: 16 }}>Cost basis</th>
          <th style={{ paddingTop: 16 }}>Profit</th>
        </tr>
      </thead>
      <tbody>
        {groups.map((group) => {
          // Matches Inventory.tsx's groupKey(): a real product_id when
          // there is one, otherwise the normalized name -- NOT a shared
          // '__unmatched__' bucket, which would give every unmatched
          // product the same React key AND the same checkbox state.
          const key = group.product_id ?? (group.name ?? 'unmatched').trim().toLowerCase()
          return (
            <tr
              key={key}
              className="row"
              onClick={() => onOpenProduct(group)}
              style={{ cursor: 'pointer' }}
            >
              <td onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" checked={checkedKeys.has(key)} onChange={() => onToggle(group)} />
              </td>
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
              <td style={{ fontWeight: 500 }}>
                {renaming === group.product_id ? (
                  <input
                    className="field-input"
                    autoFocus
                    value={draftName}
                    onChange={(e) => setDraftName(e.target.value)}
                    onBlur={() => group.product_id && saveName(group.product_id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && group.product_id) saveName(group.product_id)
                      if (e.key === 'Escape') setRenaming(undefined)
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
              </td>
              <td className="num" style={{ fontWeight: 600 }}>{group.total_units}</td>
              <td className="num" style={{ color: 'var(--text-secondary)' }}>{group.in_hand}</td>
              <td className="num" style={{ color: 'var(--text-secondary)' }}>{group.sold}</td>
              <td className="num" style={{ color: 'var(--text-secondary)' }}>
                {group.avg_sale_price != null ? money(group.avg_sale_price) : '—'}
              </td>
              <td className="num">{money(group.total_cost_basis)}</td>
              <td
                className="num"
                style={{
                  color:
                    group.total_profit == null
                      ? 'var(--text-secondary)'
                      : group.total_profit >= 0
                        ? 'var(--status-success)'
                        : 'var(--status-failed)'
                }}
              >
                {group.total_profit != null ? `${group.total_profit >= 0 ? '+' : ''}${money(group.total_profit)}` : '—'}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export default GroupedInventory
