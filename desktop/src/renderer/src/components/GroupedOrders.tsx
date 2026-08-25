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

function money(n: number | null | undefined): string {
  if (n == null) return '—'
  return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

interface GroupedOrdersProps {
  groups: OrderGroup[]
  selectedId: string | null
  onSelect: (order: Order) => void
}

function GroupedOrders({ groups, selectedId, onSelect }: GroupedOrdersProps): React.JSX.Element {
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
          <th style={{ paddingTop: 16, width: 26 }} />
          <th style={{ paddingTop: 16 }}>Order</th>
          <th style={{ paddingTop: 16 }}>Retailer</th>
          <th style={{ paddingTop: 16, textAlign: 'right' }}>Total</th>
          <th style={{ paddingTop: 16, textAlign: 'right' }}>Items</th>
          <th style={{ paddingTop: 16 }}>Status</th>
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
              // Clicking the row opens the order; only the chevron expands,
              // so a single-line order is still one click to edit.
              onClick={() => onSelect(head)}
              style={{
                cursor: 'pointer',
                background: selected
                  ? 'linear-gradient(90deg, oklch(29% 0.06 215), oklch(27% 0.06 292 / 0.6))'
                  : isOpen
                    ? 'oklch(90% 0.02 250 / 0.06)'
                    : undefined
              }}
            >
              <td
                style={{ color: 'var(--text-faint)', fontSize: 11 }}
                onClick={(e) => {
                  if (!isMulti) return
                  e.stopPropagation()
                  toggle(key)
                }}
              >
                {isMulti ? (isOpen ? '▾' : '▸') : ''}
              </td>
              <td>
                {group.orderNumber ? (
                  <span className="num" style={{ fontSize: 12.5 }}>{group.orderNumber}</span>
                ) : (
                  <span style={{ fontSize: 12.5 }}>{head.raw_product_text ?? 'Unknown item'}</span>
                )}
                <div className="num" style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 2 }}>
                  {group.orderNumber === null && 'no order number · '}
                  {head.purchased_at ? new Date(head.purchased_at).toLocaleDateString() : 'no date'}
                </div>
              </td>
              <td style={{ color: 'var(--text-secondary)', fontSize: 12.5 }}>{head.retailer ?? '—'}</td>
              <td className="num" style={{ textAlign: 'right', fontWeight: isMulti ? 600 : 400 }}>
                {group.hasPrice ? money(group.total) : <span style={{ color: 'var(--text-faint)' }}>—</span>}
              </td>
              <td className="num" style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>
                {group.itemCount}
              </td>
              <td>
                <StatusPill status={head.status} />
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
                  <td />
                  <td style={{ paddingLeft: 26, color: 'var(--text-secondary)', fontSize: 12 }}>
                    {line.raw_product_text ?? 'Unknown item'}
                  </td>
                  <td />
                  <td className="num" style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>
                    {line.unit_price != null ? money(line.unit_price * (line.quantity ?? 1)) : '—'}
                  </td>
                  <td className="num" style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>
                    {line.quantity ?? 1}
                  </td>
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
