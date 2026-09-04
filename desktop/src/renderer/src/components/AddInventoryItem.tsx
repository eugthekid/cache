import { useState } from 'react'
import { createPortal } from 'react-dom'
import { api, type InventoryStatus } from '../api/client'

interface AddInventoryItemProps {
  onClose: () => void
  onAdded: () => void
}

const ITEM_STATUSES: InventoryStatus[] = ['in_hand', 'listed', 'sold', 'returned', 'lost']

function AddInventoryItem({ onClose, onAdded }: AddInventoryItemProps): React.JSX.Element {
  const [productText, setProductText] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [status, setStatus] = useState<InventoryStatus>('in_hand')
  const [costBasis, setCostBasis] = useState('')
  const [location, setLocation] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSave = productText.trim() !== '' && Number(quantity) >= 1

  async function save(): Promise<void> {
    if (!canSave) return
    setSaving(true)
    setError(null)
    try {
      await api.inventory.create({
        product_text: productText.trim(),
        quantity: Number(quantity),
        status,
        cost_basis: costBasis ? Number(costBasis) : null,
        location: location || null,
        notes: notes || null
      })
      onAdded()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add item')
    } finally {
      setSaving(false)
    }
  }

  // Portal to escape any ancestor `.card`'s backdrop-filter, which makes
  // that card the containing block for `position: fixed` descendants
  // instead of the viewport -- see ImportWizard.tsx for the bug this
  // pattern avoids.
  return createPortal(
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'oklch(12% 0.012 260)', opacity: 0.7 }} onClick={onClose} />
      <div className="card" style={{ position: 'relative', width: 440, display: 'flex', flexDirection: 'column', gap: 16, padding: '22px 26px 24px', borderRadius: 16 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 700 }}>Add inventory item</div>
            <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 4 }}>
              For stock you already hold that never went through Cache -- no order, no import file.
            </div>
          </div>
          <button onClick={onClose} className="link-action" aria-label="Close" style={{ fontSize: 18, marginTop: 2 }}>
            ×
          </button>
        </div>

        <Field label="Product">
          <input
            className="field-input"
            value={productText}
            onChange={(e) => setProductText(e.target.value)}
            placeholder="e.g. Pokémon TCG: Prismatic Evolutions Booster Bundle"
            autoFocus
          />
        </Field>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="Quantity">
            <input className="field-input num" type="number" min={1} step="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </Field>
          <Field label="Status">
            <select className="select" value={status} onChange={(e) => setStatus(e.target.value as InventoryStatus)}>
              {ITEM_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Field label="Cost basis">
            <input className="field-input num" type="number" step="0.01" value={costBasis} onChange={(e) => setCostBasis(e.target.value)} placeholder="0.00" />
          </Field>
          <Field label="Location">
            <input className="field-input" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Closet A, Storage bin 3…" />
          </Field>
        </div>

        <Field label="Notes">
          <input className="field-input" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </Field>

        {error && <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{error}</div>}

        <button className="btn-primary" onClick={save} disabled={!canSave || saving}>
          {saving ? 'ADDING…' : quantity && Number(quantity) > 1 ? `ADD ${quantity} UNITS` : 'ADD ITEM'}
        </button>
      </div>
    </div>,
    document.body
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

export default AddInventoryItem
