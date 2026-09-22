import { type InventoryItem, type Order, type ProductGroup } from '../api/client'
import StatusPill from './StatusPill'

interface ProductDetailProps {
  group: ProductGroup
  units: InventoryItem[]
  ordersById: Map<string, Order>
  onBack: () => void
  onSelectUnit: (item: InventoryItem) => void
  selectedId: string | null
  /** Mass-select for bulk edit/duplicate/delete -- the same checkedIds
   * state and ids the "All units" screen uses, since `units` here is just
   * that same list filtered down to one product. A checkbox checked in
   * either place is the same underlying selection. */
  checkedIds: Set<string>
  onToggle: (id: string) => void
  onToggleAll: () => void
}

function money(n: number | null | undefined): string {
  if (n == null) return '—'
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/**
 * Per-unit detail for one product -- replaces the old inline "unit 1, 2, 3"
 * list. That list had nothing to actually distinguish one unit from
 * another; the things that DO -- which order it came from, where it
 * physically is, whether it sold and for how much -- are exactly the
 * columns here. A full screen rather than an inline expansion because a
 * single product can hold 90+ units (verified in real data), which reads
 * as a wall of rows inline but is a normal table on its own screen.
 */
function ProductDetail({
  group,
  units,
  ordersById,
  onBack,
  onSelectUnit,
  selectedId,
  checkedIds,
  onToggle,
  onToggleAll
}: ProductDetailProps): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 4px 14px' }}>
        <button className="btn-ghost" style={{ padding: '6px 12px', fontSize: 12 }} onClick={onBack}>
          ← Back
        </button>
        {group.image_url ? (
          <img
            src={group.image_url}
            alt=""
            style={{ width: 36, height: 36, objectFit: 'contain', borderRadius: 8, background: 'var(--field-bg)' }}
          />
        ) : (
          <div style={{ width: 36, height: 36, borderRadius: 8, background: 'var(--field-bg)' }} />
        )}
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{group.name}</div>
          <div className="num" style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
            {group.total_units} units · {group.sold} sold
            {group.avg_sale_price != null && ` · avg ${money(group.avg_sale_price)}`}
          </div>
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ paddingTop: 10, width: 32 }}>
                <input type="checkbox" checked={units.length > 0 && checkedIds.size === units.length} onChange={onToggleAll} />
              </th>
              <th style={{ paddingTop: 10 }}>Order #</th>
              <th style={{ paddingTop: 10 }}>Retailer</th>
              <th style={{ paddingTop: 10 }}>Location</th>
              <th style={{ paddingTop: 10 }}>Status</th>
              <th style={{ paddingTop: 10 }}>Purchase price</th>
              <th style={{ paddingTop: 10 }}>Sale price</th>
              <th style={{ paddingTop: 10 }}>Sold</th>
            </tr>
          </thead>
          <tbody>
            {units.map((unit) => {
              const order = unit.order_id ? ordersById.get(unit.order_id) : undefined
              return (
                <tr
                  key={unit.id}
                  className="row"
                  onClick={() => onSelectUnit(unit)}
                  style={{
                    cursor: 'pointer',
                    background:
                      unit.id === selectedId
                        ? 'linear-gradient(90deg, oklch(29% 0.06 215), oklch(27% 0.06 292 / 0.6))'
                        : undefined
                  }}
                >
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={checkedIds.has(unit.id)} onChange={() => onToggle(unit.id)} />
                  </td>
                  <td className="num" style={{ fontSize: 12.5 }}>{order?.order_number ?? (unit.order_id ? 'N/A' : 'imported')}</td>
                  <td style={{ color: 'var(--text-secondary)', fontSize: 12.5 }}>{order?.retailer ?? '—'}</td>
                  <td style={{ color: 'var(--text-secondary)', fontSize: 12.5 }}>{unit.location ?? '—'}</td>
                  <td>
                    <StatusPill status={unit.status} />
                  </td>
                  <td className="num" style={{ color: 'var(--text-secondary)' }}>{money(unit.cost_basis)}</td>
                  <td className="num">{unit.status === 'sold' ? money(unit.sold_price) : '—'}</td>
                  <td className="num" style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                    {unit.sold_at ? unit.sold_at.slice(0, 10) : '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default ProductDetail
