import { useEffect, useState } from 'react'
import {
  api,
  type ProductDashboardData,
  type ProductGroup,
  type ProductFields,
  type ProductRetailerBreakdown
} from '../api/client'
import { RetailerBadge, retailerColor } from './retailerBrand'
import ItemDetails from './ItemDetails'

interface ProductDashboardProps {
  /** Categories already in use, offered in the Category dropdown. */
  categories: string[]
  group: ProductGroup
  onBack: () => void
  /** Open straight into count editing (from a variant's "Edit counts" button). */
  startInEdit?: boolean
  /** Called after anything that changes counts, so the product list the
   * user returns to isn't showing stale totals. */
  onChanged: () => void
}

type Draft = { order_placed: string; in_transit: string; in_hand_or_sold: string }
type Stage = keyof Draft

const STAGES: { key: Stage; label: string }[] = [
  { key: 'order_placed', label: 'Order placed' },
  { key: 'in_transit', label: 'In transit' },
  { key: 'in_hand_or_sold', label: 'In hand / sold' }
]

const BAR_COLORS = {
  placed: 'var(--text-faint)',
  transit: 'var(--accent-cyan)',
  hand: 'var(--status-success)',
  sold: 'var(--accent-violet)'
}

function money(n: number): string {
  return `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function signedMoney(n: number): string {
  return `${n >= 0 ? '+' : '-'}${money(n)}`
}

function parseCount(text: string): number | null {
  if (text.trim() === '') return null
  const n = Number(text)
  return Number.isInteger(n) && n >= 0 ? n : null
}

function toDraft(r: ProductRetailerBreakdown): Draft {
  return {
    order_placed: String(r.order_placed),
    in_transit: String(r.in_transit),
    in_hand_or_sold: String(r.in_hand_or_sold)
  }
}

function todayInput(): string {
  const d = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * One product, as counts rather than units: how many you hold at each
 * stage per retailer, the totals those add up to, and a form for recording
 * a sale as "N units at $P". Replaces the per-unit table (order numbers,
 * checkboxes) for matched products -- inventory is pooled here, not tracked
 * order by order.
 *
 * "Edit counts" dims everything except the per-retailer numbers and lets
 * them be typed over directly. Nothing rebalances automatically: every
 * total, the stage bar and the average cost are just sums of what's typed,
 * so the screen always agrees with itself.
 */
function ProductDashboard({ group, categories, onBack, startInEdit, onChanged }: ProductDashboardProps): React.JSX.Element {
  const productId = group.product_id as string
  const [data, setData] = useState<ProductDashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  // Stores added during THIS edit that have no units yet, with the price
  // typed for them. They become real once the counts are saved.
  const [added, setAdded] = useState<{ retailer: string; price: string }[]>([])
  const [addChoice, setAddChoice] = useState('')

  const [qty, setQty] = useState('1')
  const [price, setPrice] = useState('')
  const [platform, setPlatform] = useState('')
  const [soldOn, setSoldOn] = useState(todayInput())
  const [selling, setSelling] = useState(false)
  const [saleError, setSaleError] = useState<string | null>(null)
  const [moveQty, setMoveQty] = useState('1')
  const [moveTo, setMoveTo] = useState('')
  const [moving, setMoving] = useState(false)
  const [moveError, setMoveError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    api.products
      .dashboard(productId)
      .then((d) => {
        if (!live) return
        setData(d)
        if (startInEdit) {
          setDrafts(Object.fromEntries(d.retailers.map((r) => [r.retailer, toDraft(r)])))
          setEditing(true)
        }
      })
      .catch((err) => live && setError(err instanceof Error ? err.message : 'Failed to load this product'))
    return () => {
      live = false
    }
  // startInEdit only matters on first load; the key on this component
  // remounts it for each variant.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productId])

  if (error) {
    return (
      <div style={{ padding: 20 }}>
        <button className="btn-ghost" style={{ padding: '6px 12px', fontSize: 12 }} onClick={onBack}>
          ← Back
        </button>
        <div style={{ marginTop: 16, fontSize: 13, color: 'var(--status-failed)' }}>{error}</div>
      </div>
    )
  }
  if (!data) {
    return <div style={{ padding: 20, fontSize: 13, color: 'var(--text-faint)' }}>Loading…</div>
  }

  const original = new Map(data.retailers.map((r) => [r.retailer, r]))
  const addable = data.addable_retailers.filter((name) => !added.some((a) => a.retailer === name))

  function startEdit(): void {
    setDrafts(Object.fromEntries(data!.retailers.map((r) => [r.retailer, toDraft(r)])))
    setSaveError(null)
    setAdded([])
    setAddChoice('')
    setEditing(true)
  }

  function cancelEdit(): void {
    setEditing(false)
    setSaveError(null)
    setAdded([])
  }

  // What each retailer's counts are RIGHT NOW: the typed draft while editing
  // (a half-typed or invalid field falls back to its saved value so totals
  // never go NaN), the saved numbers otherwise.
  let invalidField = false
  let priceMissing = false
  const cards: ProductRetailerBreakdown[] = [
    ...data.retailers,
    ...added.map((a) => {
      const price = a.price.trim() === '' ? NaN : Number(a.price)
      return {
        retailer: a.retailer,
        units: 0,
        order_placed: 0,
        in_transit: 0,
        in_hand_or_sold: 0,
        avg_unit_price: Number.isFinite(price) && price >= 0 ? price : null,
        min_unit_price: null,
        max_unit_price: null
      }
    })
  ]
  const live = cards.map((r) => {
    if (!editing) {
      return { r, order_placed: r.order_placed, in_transit: r.in_transit, in_hand_or_sold: r.in_hand_or_sold }
    }
    const d = drafts[r.retailer] ?? toDraft(r)
    const out = { r } as { r: ProductRetailerBreakdown } & Record<Stage, number>
    for (const { key } of STAGES) {
      const n = parseCount(d[key])
      if (n === null) invalidField = true
      out[key] = n ?? r[key]
    }
    return out
  })

  const placed = live.reduce((t, x) => t + x.order_placed, 0)
  const transit = live.reduce((t, x) => t + x.in_transit, 0)
  const handOrSold = live.reduce((t, x) => t + x.in_hand_or_sold, 0)
  const total = placed + transit + handOrSold
  const inHand = handOrSold - data.sold
  const invested = live.reduce(
    (t, x) => t + (x.order_placed + x.in_transit + x.in_hand_or_sold) * (x.r.avg_unit_price ?? 0),
    0
  )
  const pricedUnits = live.reduce(
    (t, x) => t + (x.r.avg_unit_price == null ? 0 : x.order_placed + x.in_transit + x.in_hand_or_sold),
    0
  )
  const avgCost = editing ? (pricedUnits ? invested / pricedUnits : null) : data.avg_cost
  const investedShown = editing ? invested : data.invested

  const belowSold = editing && inHand < 0
  const zero = { units: 0, order_placed: 0, in_transit: 0, in_hand_or_sold: 0 }
  live.forEach((x) => {
    if (added.some((a) => a.retailer === x.r.retailer) && x.order_placed + x.in_transit + x.in_hand_or_sold > 0 && x.r.avg_unit_price == null) {
      priceMissing = true
    }
  })
  const changes = live
    .map((x) => {
      const o = original.get(x.r.retailer) ?? zero
      const parts = STAGES.map(({ key, label }) => {
        const d = x[key] - o[key]
        return d ? `${d > 0 ? '+' : '-'}${Math.abs(d)} ${label.toLowerCase()}` : null
      }).filter(Boolean)
      if (!parts.length) return null
      const after = x.order_placed + x.in_transit + x.in_hand_or_sold
      return `${x.r.retailer}: ${parts.join(', ')} · ${o.units} → ${after} units`
    })
    .filter(Boolean)
  const canSave = editing && !invalidField && !belowSold && !priceMissing && changes.length > 0

  async function saveCounts(): Promise<void> {
    if (!canSave) return
    setSaving(true)
    setSaveError(null)
    try {
      const edits = live
        .filter((x) => {
          const o = original.get(x.r.retailer) ?? zero
          return STAGES.some(({ key }) => x[key] !== o[key])
        })
        .map((x) => ({
          retailer: x.r.retailer,
          order_placed: x.order_placed,
          in_transit: x.in_transit,
          in_hand_or_sold: x.in_hand_or_sold,
          unit_price: added.some((a) => a.retailer === x.r.retailer) ? x.r.avg_unit_price : undefined
        }))
      setData(await api.products.updateCounts(productId, edits))
      setEditing(false)
      onChanged()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save counts')
    } finally {
      setSaving(false)
    }
  }

  const saleQty = Number(qty)
  const salePrice = Number(price)
  const saleValid = Number.isInteger(saleQty) && saleQty >= 1 && saleQty <= inHand && price.trim() !== '' && salePrice >= 0
  const salePreview =
    saleValid && avgCost != null
      ? `Revenue ${money(saleQty * salePrice)} · cost ${money(saleQty * avgCost)} · profit ${signedMoney(saleQty * (salePrice - avgCost))}`
      : ''
  const saleHint =
    inHand < 1
      ? 'No units in hand to sell.'
      : Number.isInteger(saleQty) && saleQty >= 1 && saleQty <= inHand
        ? ''
        : `Enter a quantity from 1 to ${inHand}, the number in hand.`

  async function recordSale(): Promise<void> {
    if (!saleValid) return
    setSelling(true)
    setSaleError(null)
    try {
      setData(
        await api.products.recordSale(productId, {
          quantity: saleQty,
          unit_price: salePrice,
          platform: platform.trim() || null,
          sold_at: soldOn ? new Date(`${soldOn}T12:00:00`).toISOString() : null
        })
      )
      setQty('1')
      onChanged()
    } catch (err) {
      setSaleError(err instanceof Error ? err.message : 'Failed to record the sale')
    } finally {
      setSelling(false)
    }
  }

  async function saveFields(fields: ProductFields): Promise<void> {
    try {
      await api.products.update(productId, fields)
      setData(await api.products.dashboard(productId))
      onChanged()
    } catch (err) {
      setSaleError(err instanceof Error ? err.message : 'That didn’t save')
    }
  }

  const specificSiblings = data.siblings.filter((x) => x.product_id !== productId && x.variant_kind === 'specific')
  // Variants you could still turn random units into that have no product yet
  // (a random tin named "Sylveon or Greninja" before you hold either).
  const newVariants = (data.variant_hint?.kind === 'random' ? data.variant_hint.others : []).filter((o) => !o.product_id)
  const unsold = data.total_units - data.sold
  const moveCount = Number(moveQty)
  const moveValid = Number.isInteger(moveCount) && moveCount >= 1 && moveCount <= unsold && moveTo !== ''

  async function moveUnits(): Promise<void> {
    if (!moveValid) return
    setMoving(true)
    setMoveError(null)
    try {
      setData(
        await api.products.resolve(
          productId,
          moveTo.startsWith('new:') ? { variant: moveTo.slice(4) } : { productId: moveTo },
          moveCount
        )
      )
      setMoveTo('')
      setMoveQty('1')
      onChanged()
    } catch (err) {
      setMoveError(err instanceof Error ? err.message : 'Couldn’t move those units')
    } finally {
      setMoving(false)
    }
  }

  async function undoSale(saleId: string): Promise<void> {
    setSaleError(null)
    try {
      setData(await api.products.undoSale(productId, saleId))
      onChanged()
    } catch (err) {
      setSaleError(err instanceof Error ? err.message : 'Failed to undo the sale')
    }
  }

  const dim = (extra: React.CSSProperties = {}): React.CSSProperties => ({
    ...extra,
    opacity: editing ? 0.35 : 1,
    pointerEvents: editing ? 'none' : undefined,
    transition: 'opacity 0.15s ease'
  })

  const tile = (label: string, value: number | string, color?: string): React.JSX.Element => (
    <div style={{ background: 'var(--field-bg)', borderRadius: 10, padding: '11px 13px' }}>
      <div className="field-label">{label}</div>
      <div className="num" style={{ fontSize: 20, fontWeight: 500, marginTop: 3, color }}>
        {value}
      </div>
    </div>
  )

  const segments = [
    { label: 'Order placed', value: placed, color: BAR_COLORS.placed },
    { label: 'In transit', value: transit, color: BAR_COLORS.transit },
    { label: 'In hand', value: Math.max(inHand, 0), color: BAR_COLORS.hand },
    { label: 'Sold', value: data.sold, color: BAR_COLORS.sold }
  ]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '10px 4px 20px', overflow: 'auto', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={dim({ display: 'flex', alignItems: 'center', gap: 12, flex: 1, minWidth: 0 })}>
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
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>{data.name}</div>
            {(data.set_name || data.series_name) && (
              <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                {[data.series_name, data.set_name].filter(Boolean).join(' · ')}
              </div>
            )}
            {data.family ? (
              <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                {data.variant_kind === 'random' ? 'Random variant' : 'Variant'} of {data.family.name}
              </div>
            ) : (
              data.variant_hint && (
                <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
                  {data.variant_hint.kind === 'random' ? 'Random variant' : `Variant: ${data.variant_hint.variant}`}
                </div>
              )
            )}
            <div className="num" style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
              {total} units
              {avgCost != null && ` · avg cost ${money(avgCost)}`}
              {` · ${money(investedShown)} invested`}
            </div>
          </div>
        </div>
        {editing ? (
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn-ghost" style={{ padding: '7px 14px', fontSize: 12 }} onClick={cancelEdit}>
              Cancel
            </button>
            <button
              className="btn-primary"
              style={{ padding: '7px 14px', fontSize: 12 }}
              onClick={saveCounts}
              disabled={!canSave || saving}
            >
              {saving ? 'Saving…' : 'Save counts'}
            </button>
          </div>
        ) : (
          <button className="btn-ghost" style={{ padding: '7px 14px', fontSize: 12 }} onClick={startEdit}>
            Edit counts
          </button>
        )}
      </div>

      <div style={dim()}>
        <ItemDetails
          productType={data.product_type}
          category={data.category}
          variantKind={data.variant_kind}
          categories={categories}
          onChange={saveFields}
        />
      </div>

      <div style={dim({ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 8 })}>
        {tile('In hand', Math.max(inHand, 0), 'var(--status-success)')}
        {tile('In transit', transit)}
        {tile('Order placed', placed)}
        {tile('Sold', data.sold)}
        {tile('Total bought', total)}
      </div>

      <div style={dim()}>
        <div style={{ display: 'flex', height: 10, borderRadius: 5, overflow: 'hidden', background: 'var(--field-bg)' }}>
          {segments.map((s) => (
            <div
              key={s.label}
              style={{ width: `${total ? (s.value / total) * 100 : 0}%`, background: s.color }}
              title={`${s.label} ${s.value}`}
            />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 7, fontSize: 11.5, color: 'var(--text-secondary)' }}>
          {segments.map((s) => (
            <span key={s.label}>
              <span
                style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 2, marginRight: 6, background: s.color }}
              />
              {s.label} {s.value}
            </span>
          ))}
        </div>
      </div>

      <div>
        <div className="field-label" style={dim({ marginBottom: 8 })}>
          By retailer
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
          {live.map((x) => {
            const r = x.r
            const units = x.order_placed + x.in_transit + x.in_hand_or_sold
            const isAdded = added.some((a) => a.retailer === r.retailer)
            const ranged = r.min_unit_price != null && r.max_unit_price != null && Math.abs(r.max_unit_price - r.min_unit_price) > 0.005
            return (
              <div key={r.retailer} className="card" style={{ padding: '14px 16px' }}>
                <div style={dim()}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13.5, fontWeight: 600, color: retailerColor(r.retailer) ?? undefined }}>
                      <RetailerBadge name={r.retailer} size={22} />
                      {r.retailer}
                    </div>
                    <div className="num" style={{ fontSize: 18, fontWeight: 500 }}>
                      {units} <span style={{ fontSize: 11.5, color: 'var(--text-faint)', fontWeight: 400 }}>units</span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 12 }}>
                    <span style={{ color: 'var(--text-faint)' }}>Unit price</span>
                    {isAdded ? (
                      <span style={{ color: 'var(--text-faint)' }}>set below</span>
                    ) : (
                    <span className="num">
                      {r.avg_unit_price != null ? money(r.avg_unit_price) : '—'}
                      {ranged && r.min_unit_price != null && r.max_unit_price != null && (
                        <span style={{ color: 'var(--text-faint)' }}>
                          {' '}
                          avg · {money(r.min_unit_price)}–{money(r.max_unit_price)}
                        </span>
                      )}
                    </span>
                    )}
                  </div>
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                    columnGap: 8,
                    rowGap: 5,
                    marginTop: 12,
                    paddingTop: 10,
                    borderTop: '1px solid var(--divider)'
                  }}
                >
                  {STAGES.map(({ label }) => (
                    <span key={label} className="field-label">
                      {label}
                    </span>
                  ))}
                  {STAGES.map(({ key, label }) =>
                    editing ? (
                      <input
                        key={key}
                        aria-label={`${r.retailer} ${label.toLowerCase()}`}
                        className="field-input num"
                        type="number"
                        min={0}
                        step={1}
                        value={drafts[r.retailer]?.[key] ?? String(r[key])}
                        onChange={(e) =>
                          setDrafts((prev) => ({
                            ...prev,
                            [r.retailer]: { ...(prev[r.retailer] ?? toDraft(r)), [key]: e.target.value }
                          }))
                        }
                        style={{
                          fontSize: 15,
                          fontWeight: 500,
                          padding: '5px 8px',
                          border: '1.5px solid var(--accent-cyan)',
                          background: 'oklch(78% 0.12 215 / 0.14)'
                        }}
                      />
                    ) : (
                      <div key={key} className="num" style={{ fontSize: 16, fontWeight: 500 }}>
                        {x[key]}
                      </div>
                    )
                  )}
                </div>
                {isAdded && editing && (
                  <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, marginTop: 10 }}>
                    <label style={{ flex: 1 }}>
                      <span className="field-label">Unit price (what each cost)</span>
                      <input
                        className="field-input num"
                        type="number"
                        min={0}
                        step="0.01"
                        placeholder="0.00"
                        value={added.find((a) => a.retailer === r.retailer)?.price ?? ''}
                        onChange={(e) =>
                          setAdded((prev) => prev.map((a) => (a.retailer === r.retailer ? { ...a, price: e.target.value } : a)))
                        }
                        style={{
                          marginTop: 4,
                          fontSize: 15,
                          fontWeight: 500,
                          padding: '5px 8px',
                          border: '1.5px solid var(--accent-cyan)',
                          background: 'oklch(78% 0.12 215 / 0.14)'
                        }}
                      />
                    </label>
                    <button
                      className="link-action"
                      style={{ fontSize: 11.5, paddingBottom: 8 }}
                      onClick={() => setAdded((prev) => prev.filter((a) => a.retailer !== r.retailer))}
                    >
                      Remove
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
        {editing && addable.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
            <select
              className="field-input"
              aria-label="Retailer to add"
              value={addChoice}
              onChange={(e) => setAddChoice(e.target.value)}
              style={{ width: 'auto', minWidth: 200, height: 32, padding: '0 12px', fontSize: 12.5 }}
            >
              <option value="">Add a retailer…</option>
              {addable.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            <button
              className="btn-ghost"
              style={{ padding: '7px 14px', fontSize: 12 }}
              disabled={!addChoice}
              onClick={() => {
                setAdded((prev) => [...prev, { retailer: addChoice, price: '' }])
                setDrafts((prev) => ({
                  ...prev,
                  [addChoice]: { order_placed: '0', in_transit: '0', in_hand_or_sold: '0' }
                }))
                setAddChoice('')
              }}
            >
              Add
            </button>
          </div>
        )}
        {editing && (
          <div
            style={{
              minHeight: 18,
              marginTop: 10,
              fontSize: 12,
              color: invalidField || belowSold || priceMissing || saveError ? 'var(--status-failed)' : 'var(--text-secondary)'
            }}
          >
            {saveError ??
              (invalidField
                ? 'Counts must be whole numbers, 0 or more.'
                : priceMissing
                  ? 'Enter what each unit cost for the retailer you added.'
                  : belowSold
                  ? `In hand / sold can't be lower than the ${data.sold} you've recorded as sold.`
                  : changes.length
                    ? changes.join('  |  ')
                    : 'Type the counts you actually have. Totals update as you go.')}
          </div>
        )}
      </div>

      {data.variant_kind === 'random' && specificSiblings.length + newVariants.length > 0 && (
        <div className="card" style={dim({ padding: '16px 18px' })}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>Opened some?</div>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', margin: '4px 0 12px' }}>
            Once you know which variant these turned out to be, move them there. They keep their order, retailer and
            price, and the counts here and on that version update.
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <label>
              <div className="field-label">Units</div>
              <input
                className="field-input num"
                type="number"
                min={1}
                max={unsold}
                step={1}
                value={moveQty}
                onChange={(e) => setMoveQty(e.target.value)}
                style={{ marginTop: 4, width: 90 }}
              />
            </label>
            <label>
              <div className="field-label">Turned out to be</div>
              <select
                className="field-input"
                value={moveTo}
                onChange={(e) => setMoveTo(e.target.value)}
                style={{ marginTop: 4, minWidth: 200, height: 36 }}
              >
                <option value="">Pick a variant…</option>
                {specificSiblings.map((x) => (
                  <option key={x.product_id} value={x.product_id}>
                    {x.label}
                  </option>
                ))}
                {newVariants.map((o) => (
                  <option key={o.label} value={`new:${o.label}`}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <button className="btn-ghost" style={{ padding: '8px 16px', fontSize: 12.5 }} onClick={moveUnits} disabled={!moveValid || moving}>
              {moving ? 'Moving…' : 'Move units'}
            </button>
          </div>
          <div style={{ minHeight: 16, marginTop: 8, fontSize: 12, color: 'var(--status-failed)' }}>
            {moveError ?? (moveQty !== '' && !moveValid && moveTo ? `Enter 1 to ${unsold}, the number of unsold units here.` : '')}
          </div>
        </div>
      )}

      {data.variant_hint?.kind === 'specific' && data.variant_hint.others.length > 0 && !data.family && (
        <div className="card" style={dim({ padding: '14px 18px' })}>
          <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 8 }}>Other variants</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {data.variant_hint.others.map((o) => (
              <span
                key={o.label}
                style={{
                  padding: '4px 11px',
                  borderRadius: 999,
                  fontSize: 12,
                  background: 'var(--field-bg)',
                  color: o.product_id ? 'var(--text-secondary)' : 'var(--text-faint)'
                }}
              >
                {o.label}
                <span style={{ marginLeft: 7, fontSize: 11, opacity: 0.8 }}>{o.product_id ? 'owned' : 'none bought'}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="card" style={dim({ padding: '16px 18px' })}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>Record a sale</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
            {avgCost != null ? `Costed at the average, ${money(avgCost)} each` : 'No purchase cost recorded'}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '90px minmax(0, 1fr) minmax(0, 1fr) 150px', gap: 10 }}>
          <label>
            <div className="field-label">Quantity</div>
            <input className="field-input num" type="number" min={1} step={1} value={qty} onChange={(e) => setQty(e.target.value)} style={{ marginTop: 4 }} />
          </label>
          <label>
            <div className="field-label">Price each</div>
            <input className="field-input num" type="number" min={0} step="0.01" value={price} placeholder="0.00" onChange={(e) => setPrice(e.target.value)} style={{ marginTop: 4 }} />
          </label>
          <label>
            <div className="field-label">Sold on</div>
            <input
              className="field-input"
              list="sales-channels"
              value={platform}
              placeholder="Pick or type a channel"
              onChange={(e) => setPlatform(e.target.value)}
              style={{ marginTop: 4 }}
            />
            <datalist id="sales-channels">
              {data.channels.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
          </label>
          <label>
            <div className="field-label">Date</div>
            <input className="field-input" type="date" value={soldOn} onChange={(e) => setSoldOn(e.target.value)} style={{ marginTop: 4 }} />
          </label>
        </div>
        <div style={{ minHeight: 16, marginTop: 8, fontSize: 12, color: 'var(--status-failed)' }}>{saleError ?? saleHint}</div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginTop: 6 }}>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{salePreview}</div>
          <button className="btn-primary" style={{ padding: '8px 16px', fontSize: 12.5 }} onClick={recordSale} disabled={!saleValid || selling}>
            {selling ? 'Recording…' : 'Record sale'}
          </button>
        </div>
      </div>

      <div className="card" style={dim({ padding: '16px 18px' })}>
        <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 8 }}>Sales</div>
        {data.sales.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
            Each sale you record shows here as one line with quantity, price, platform and profit, and can be undone.
          </div>
        ) : (
          data.sales.map((s) => (
            <div
              key={s.id}
              style={{
                display: 'grid',
                gridTemplateColumns: '90px 1fr 110px 90px auto',
                gap: 10,
                alignItems: 'center',
                padding: '9px 0',
                borderTop: '1px solid var(--divider)',
                fontSize: 12.5
              }}
            >
              <span className="num" style={{ color: 'var(--text-secondary)' }}>
                {s.sold_at.slice(0, 10)}
              </span>
              <span className="num">
                {s.quantity} × {money(s.unit_price)}
              </span>
              <span style={{ color: 'var(--text-secondary)' }}>{s.platform ?? '—'}</span>
              <span
                className="num"
                style={{ color: s.profit == null ? 'var(--text-faint)' : s.profit >= 0 ? 'var(--status-success)' : 'var(--status-failed)' }}
              >
                {s.profit == null ? '—' : signedMoney(s.profit)}
              </span>
              <button className="link-action" style={{ fontSize: 11.5 }} onClick={() => undoSale(s.id)}>
                Undo
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default ProductDashboard
