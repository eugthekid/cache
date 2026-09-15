import { useState } from 'react'
import { createPortal } from 'react-dom'
import { type InventoryItemUpdate, type InventoryStatus } from '../api/client'

interface BulkEditItemsProps {
  count: number
  onClose: () => void
  onSaved: () => Promise<void>
  onApply: (patch: InventoryItemUpdate) => Promise<void>
}

const ITEM_STATUSES: InventoryStatus[] = ['in_hand', 'listed', 'sold', 'returned', 'lost']

function FieldRow({ label, children }: { label: string; children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div className="field-label" style={{ width: 96, flexShrink: 0 }}>
        {label}
      </div>
      <div style={{ flex: 1 }}>{children}</div>
    </div>
  )
}

/**
 * Mass-apply a change across a checkbox selection -- the flip side of the
 * single-unit edit panel, and it mirrors that panel's shape: Status sits
 * at the top and decides which other fields are even shown, because
 * listing/sale details only mean something at the matching stage.
 * Location is hidden for sold units -- where a unit physically is stops
 * being the seller's concern once it ships.
 *
 * No per-field opt-in: whatever you fill in gets applied, whatever you
 * leave blank is untouched on every selected unit. (The tradeoff is you
 * can't bulk-CLEAR a field back to empty -- rare enough to do per-item.)
 *
 * "Retailer" isn't a field here on purpose: it's an Order property, not a
 * per-unit one. Location is the closest per-unit analog.
 */
function BulkEditItems({ count, onClose, onSaved, onApply }: BulkEditItemsProps): React.JSX.Element {
  const [status, setStatus] = useState<InventoryStatus | ''>('')
  const [costBasis, setCostBasis] = useState('')
  const [location, setLocation] = useState('')
  const [listedPrice, setListedPrice] = useState('')
  const [listedPlatform, setListedPlatform] = useState('')
  const [soldPrice, setSoldPrice] = useState('')
  const [soldPlatform, setSoldPlatform] = useState('')
  const [soldAt, setSoldAt] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const showListed = status === 'listed'
  const showSold = status === 'sold'
  const showLocation = status !== 'sold'

  const anyChange =
    status !== '' ||
    costBasis.trim() !== '' ||
    notes.trim() !== '' ||
    (showLocation && location.trim() !== '') ||
    (showListed && [listedPrice, listedPlatform].some((v) => v.trim() !== '')) ||
    (showSold && [soldPrice, soldPlatform, soldAt].some((v) => v.trim() !== ''))

  async function save(): Promise<void> {
    if (!anyChange) return
    setSaving(true)
    setError(null)
    try {
      const patch: InventoryItemUpdate = {}
      if (status !== '') patch.status = status
      if (costBasis.trim() !== '') patch.cost_basis = Number(costBasis)
      if (showLocation && location.trim() !== '') patch.location = location
      if (notes.trim() !== '') patch.notes = notes
      if (showListed) {
        if (listedPrice.trim() !== '') patch.listed_price = Number(listedPrice)
        if (listedPlatform.trim() !== '') patch.listed_platform = listedPlatform
      }
      if (showSold) {
        if (soldPrice.trim() !== '') patch.sold_price = Number(soldPrice)
        if (soldPlatform.trim() !== '') patch.sold_platform = soldPlatform
        if (soldAt.trim() !== '') patch.sold_at = new Date(soldAt).toISOString()
      }
      await onApply(patch)
      await onSaved()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply changes')
    } finally {
      setSaving(false)
    }
  }

  return createPortal(
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'oklch(12% 0.012 260)', opacity: 0.7 }} onClick={onClose} />
      <div className="card" style={{ position: 'relative', width: 460, maxHeight: '88vh', display: 'flex', flexDirection: 'column', gap: 14, padding: '22px 26px 24px', borderRadius: 16 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 700 }}>
              Bulk edit {count} unit{count === 1 ? '' : 's'}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 4 }}>
              Fill in only what you want to change. Blank fields are left as-is on every selected unit.
            </div>
          </div>
          <button onClick={onClose} className="link-action" aria-label="Close" style={{ fontSize: 18, marginTop: 2 }}>
            ×
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, overflow: 'auto', paddingRight: 2 }}>
          <FieldRow label="Status">
            <select className="select" value={status} onChange={(e) => setStatus(e.target.value as InventoryStatus | '')}>
              <option value="">— keep current —</option>
              {ITEM_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </FieldRow>

          <div style={{ borderTop: '1px solid var(--divider)', margin: '2px 0' }} />

          <FieldRow label="Price">
            <input className="field-input num" type="number" step="0.01" value={costBasis} onChange={(e) => setCostBasis(e.target.value)} placeholder="0.00" />
          </FieldRow>

          {showLocation && (
            <FieldRow label="Location">
              <input className="field-input" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Closet A, Storage bin 3…" />
            </FieldRow>
          )}

          {showListed && (
            <>
              <FieldRow label="Listed price">
                <input className="field-input num" type="number" step="0.01" value={listedPrice} onChange={(e) => setListedPrice(e.target.value)} placeholder="0.00" />
              </FieldRow>
              <FieldRow label="Listed on">
                <input className="field-input" value={listedPlatform} onChange={(e) => setListedPlatform(e.target.value)} placeholder="eBay" />
              </FieldRow>
            </>
          )}

          {showSold && (
            <>
              <FieldRow label="Sold price">
                <input className="field-input num" type="number" step="0.01" value={soldPrice} onChange={(e) => setSoldPrice(e.target.value)} placeholder="0.00" />
              </FieldRow>
              <FieldRow label="Sold on">
                <input className="field-input" value={soldPlatform} onChange={(e) => setSoldPlatform(e.target.value)} placeholder="StockX" />
              </FieldRow>
              <FieldRow label="Sold date">
                <input className="field-input num" type="date" value={soldAt} onChange={(e) => setSoldAt(e.target.value)} />
              </FieldRow>
            </>
          )}

          <FieldRow label="Notes">
            <input className="field-input" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </FieldRow>
        </div>

        {error && <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{error}</div>}

        <button className="btn-primary" onClick={save} disabled={!anyChange || saving}>
          {saving ? 'APPLYING…' : `APPLY TO ${count} UNIT${count === 1 ? '' : 'S'}`}
        </button>
      </div>
    </div>,
    document.body
  )
}

export default BulkEditItems
