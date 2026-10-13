import { useState } from 'react'
import type { Order } from '../api/client'
import StatusPill from './StatusPill'

export interface OrderGroup {
  /** The retailer's order number, or null for attempts that never got one. */
  orderNumber: string | null
  lines: Order[]
  total: number
  itemCount: number
  /** False when NO line carried a price. Some bots (Shikari on Target)
   * never report one, and rendering those as "$0.00" would claim the order
   * was free rather than that we don't know what it cost. */
  hasPrice: boolean
}

/**
 * Collapses the order list into one row per PURCHASE.
 *
 * One retailer order can arrive as several Discord messages -- one per
 * product in the cart -- so the flat list showed a three-item cart as three
 * unrelated rows, none of which told you what the order actually cost.
 * Verified in real data: 50 order numbers span multiple rows.
 *
 * Grouping keys on order_number because that IS the retailer's identity for
 * a purchase. Failed attempts never get one (nothing was bought), so they
 * stay as individual rows rather than being lumped into a fake "no number"
 * cart -- which is also correct: each failed attempt is its own event.
 */
export function groupOrders(orders: Order[]): OrderGroup[] {
  const groups: OrderGroup[] = []
  const byNumber = new Map<string, OrderGroup>()

  for (const order of orders) {
    const lineTotal = (order.unit_price ?? 0) * (order.quantity ?? 1)
    const number = order.order_number?.trim()

    if (!number) {
      groups.push({
        orderNumber: null,
        lines: [order],
        total: lineTotal,
        itemCount: order.quantity ?? 1,
        hasPrice: order.unit_price != null
      })
      continue
    }
    const existing = byNumber.get(number)
    if (existing) {
      existing.lines.push(order)
      existing.total += lineTotal
      existing.itemCount += order.quantity ?? 1
      existing.hasPrice = existing.hasPrice || order.unit_price != null
    } else {
      const group: OrderGroup = {
        orderNumber: number,
        lines: [order],
        total: lineTotal,
        itemCount: order.quantity ?? 1,
        hasPrice: order.unit_price != null
      }
      byNumber.set(number, group)
      groups.push(group)
    }
  }
  return groups
}

/**
 * Re-sorts groups by CART total for price sorts.
 *
 * The server sorts individual lines by unit_price, which is right for the
 * flat view but reads as broken once rows are grouped: a $161.64 single-line
 * order would sit above a $281.62 three-line cart, because the server only
 * ever compared the line prices. Rows must be ordered by the number they
 * actually display. Other sorts (date, name) need no fixup -- every line in
 * a cart shares those values, verified in real data.
 */
export function sortGroups(groups: OrderGroup[], sort: string): OrderGroup[] {
  if (sort !== 'price_desc' && sort !== 'price_asc') return groups
  const dir = sort === 'price_desc' ? -1 : 1
  return [...groups].sort((a, b) => {
    if (a.hasPrice !== b.hasPrice) return a.hasPrice ? -1 : 1 // unpriced last
    return (a.total - b.total) * dir
  })
}

/** Every column after Product is centered and given room to breathe. */
const CELL: React.CSSProperties = { textAlign: 'center', padding: '11px 12px', whiteSpace: 'nowrap' }

function money(n: number | null | undefined): string {
  if (n == null) return '—'
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

interface GroupedOrdersProps {
  groups: OrderGroup[]
  selectedId: string | null
  onSelect: (order: Order) => void
  /** Ids of every checked LINE. A cart's checkbox is derived from its
   * lines, so selecting a cart is just selecting all of them -- which is
   * what lets the bulk bar cancel or delete a whole purchase at once. */
  checkedIds: Set<string>
  /** Selects every id given, or clears them if they were all already
   * selected -- one call serves a line, a cart, and the header checkbox. */
  onToggleLines: (ids: string[]) => void
}

function GroupCheckbox({
  ids,
  checkedIds,
  onToggleLines
}: {
  ids: string[]
  checkedIds: Set<string>
  onToggleLines: (ids: string[]) => void
}): React.JSX.Element {
  const checkedCount = ids.filter((id) => checkedIds.has(id)).length
  return (
    <input
      type="checkbox"
      checked={ids.length > 0 && checkedCount === ids.length}
      ref={(el) => {
        if (el) el.indeterminate = checkedCount > 0 && checkedCount < ids.length
      }}
      onChange={() => onToggleLines(ids)}
    />
  )
}

function GroupedOrders({
  groups,
  selectedId,
  onSelect,
  checkedIds,
  onToggleLines
}: GroupedOrdersProps): React.JSX.Element {
  const allIds = groups.flatMap((g) => g.lines.map((l) => l.id))
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  function toggle(key: string): void {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead>
        <tr>
          <th style={{ paddingTop: 16, width: 32 }}>
            <GroupCheckbox ids={allIds} checkedIds={checkedIds} onToggleLines={onToggleLines} />
          </th>
          <th style={{ paddingTop: 16, width: 26 }} />
          <th style={{ paddingTop: 16, minWidth: 230 }}>Product</th>
          {['Order #', 'Retailer', 'Profile', 'Total', 'Items', 'Status', 'Shipping'].map((h) => (
            <th key={h} style={{ paddingTop: 16, ...CELL }}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {groups.flatMap((group) => {
          const head = group.lines[0]
          const key = group.orderNumber ?? head.id
          const isMulti = group.lines.length > 1
          const isOpen = expanded.has(key)
          const selected = group.lines.some((l) => l.id === selectedId)

          const rows = [
            <tr
              key={key}
              className="row"
              // Multi-line orders expand to show their products on a row
              // click; a single-line order has nothing extra to reveal,
              // so it goes straight to edit instead.
              onClick={() => (isMulti ? toggle(key) : onSelect(head))}
              style={{
                cursor: 'pointer',
                background: selected
                  ? 'linear-gradient(90deg, oklch(29% 0.06 215), oklch(27% 0.06 292 / 0.6))'
                  : isOpen
                    ? 'oklch(90% 0.02 250 / 0.06)'
                    : undefined
              }}
            >
              <td onClick={(e) => e.stopPropagation()}>
                <GroupCheckbox ids={group.lines.map((l) => l.id)} checkedIds={checkedIds} onToggleLines={onToggleLines} />
              </td>
              <td style={{ color: 'var(--text-faint)', fontSize: 11 }}>{isMulti ? (isOpen ? '▾' : '▸') : ''}</td>
              <td>
                <span style={{ fontSize: 12.5, fontWeight: isMulti ? 600 : 400 }}>
                  {isMulti ? `${group.lines.length} products` : (head.product_name ?? head.raw_product_text ?? 'Unknown item')}
                </span>
                <div className="num" style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 2 }}>
                  {head.purchased_at ? new Date(head.purchased_at).toLocaleDateString() : 'no date'}
                </div>
              </td>
              <td className="num" style={{ fontSize: 12.5, color: 'var(--text-secondary)', ...CELL }}>
                {group.orderNumber ?? 'N/A'}
              </td>
              <td style={{ color: 'var(--text-secondary)', fontSize: 12.5, ...CELL }}>{head.retailer ?? '—'}</td>
              <td style={{ color: 'var(--text-secondary)', fontSize: 12.5, ...CELL }}>{head.profile ?? '—'}</td>
              <td className="num" style={{ fontWeight: isMulti ? 600 : 400, ...CELL }}>
                {group.hasPrice ? money(group.total) : <span style={{ color: 'var(--text-faint)' }}>—</span>}
              </td>
              <td className="num" style={{ color: 'var(--text-secondary)', ...CELL }}>
                {group.itemCount}
              </td>
              <td style={CELL}>
                <StatusPill status={head.status} />
              </td>
              <td style={CELL}>
                {/* Shipping only means something for an order that went
                    through; a failed or cancelled one never ships. */}
                {head.status === 'success' || head.status === 'pending' ? (
                  <StatusPill status={head.shipping_status} />
                ) : (
                  <span style={{ color: 'var(--text-faint)' }}>—</span>
                )}
              </td>
            </tr>
          ]

          if (isMulti && isOpen) {
            for (const line of group.lines) {
              rows.push(
                <tr
                  key={line.id}
                  className="row"
                  onClick={() => onSelect(line)}
                  style={{
                    cursor: 'pointer',
                    background:
                      line.id === selectedId
                        ? 'linear-gradient(90deg, oklch(29% 0.06 215), oklch(27% 0.06 292 / 0.6))'
                        : 'oklch(15% 0.012 255 / 0.35)'
                  }}
                >
                  <td onClick={(e) => e.stopPropagation()}>
                    <GroupCheckbox ids={[line.id]} checkedIds={checkedIds} onToggleLines={onToggleLines} />
                  </td>
                  <td />
                  <td style={{ paddingLeft: 26, color: 'var(--text-secondary)', fontSize: 12 }}>
                    {line.product_name ?? line.raw_product_text ?? 'Unknown item'}
                  </td>
                  <td />
                  <td />
                  <td />
                  <td className="num" style={{ color: 'var(--text-secondary)', ...CELL }}>
                    {line.unit_price != null ? money(line.unit_price * (line.quantity ?? 1)) : '—'}
                  </td>
                  <td className="num" style={{ color: 'var(--text-secondary)', ...CELL }}>
                    {line.quantity ?? 1}
                  </td>
                  <td />
                  <td />
                </tr>
              )
            }
          }
          return rows
        })}
      </tbody>
    </table>
  )
}

export default GroupedOrders
