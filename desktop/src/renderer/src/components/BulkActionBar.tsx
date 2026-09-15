import { useState } from 'react'

interface BulkActionBarProps<S extends string> {
  count: number
  onDelete: () => Promise<void>
  /** Status dropdown + SET STATUS button. Optional -- Orders passes it
   * (its only bulk field-change), Inventory doesn't: there, status lives
   * at the top of the bulk-edit modal, since it decides which other
   * fields are even relevant. */
  statusOptions?: S[]
  onSetStatus?: (status: S) => Promise<void>
  /** Optional -- only Inventory offers this today, so Orders' bar (which
   * doesn't pass it) renders without a Duplicate button at all. */
  onDuplicate?: () => Promise<void>
  /** Opens the multi-field bulk-edit modal. Optional for the same reason
   * onDuplicate is. */
  onOpenBulkEdit?: () => void
  onClear: () => void
  noun: string
}

/** The row that appears above a table once one or more checkboxes are
 * checked. Shared by Orders and Inventory; each screen opts into the
 * actions it supports via the optional props. */
function BulkActionBar<S extends string>({
  count,
  statusOptions,
  onSetStatus,
  onDelete,
  onDuplicate,
  onOpenBulkEdit,
  onClear,
  noun
}: BulkActionBarProps<S>): React.JSX.Element {
  const [status, setStatus] = useState<S | ''>(statusOptions?.[0] ?? '')
  const [busy, setBusy] = useState(false)

  async function applyStatus(): Promise<void> {
    if (!onSetStatus || status === '') return
    setBusy(true)
    try {
      await onSetStatus(status)
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(): Promise<void> {
    if (!window.confirm(`Delete ${count} ${noun}${count === 1 ? '' : 's'}? A Discord resync won't bring them back — use Rebuild in Settings if you want them again.`)) return
    setBusy(true)
    try {
      await onDelete()
    } finally {
      setBusy(false)
    }
  }

  async function handleDuplicate(): Promise<void> {
    if (!onDuplicate) return
    setBusy(true)
    try {
      await onDuplicate()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="card"
      style={{
        padding: '10px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        background: 'linear-gradient(90deg, oklch(29% 0.06 215 / 0.5), oklch(27% 0.06 292 / 0.35))'
      }}
    >
      <div style={{ fontSize: 12.5, fontWeight: 600 }}>
        {count} {noun}
        {count === 1 ? '' : 's'} selected
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto' }}>
        {statusOptions && onSetStatus && (
          <>
            <select className="select" style={{ width: 160 }} value={status} onChange={(e) => setStatus(e.target.value as S)} disabled={busy}>
              {statusOptions.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={applyStatus} disabled={busy}>
              SET STATUS
            </button>
          </>
        )}
        {onOpenBulkEdit && (
          <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={onOpenBulkEdit} disabled={busy}>
            EDIT
          </button>
        )}
        {onDuplicate && (
          <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={handleDuplicate} disabled={busy}>
            DUPLICATE
          </button>
        )}
        <button className="btn-danger" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={handleDelete} disabled={busy}>
          DELETE
        </button>
        <button className="link-action" onClick={onClear} disabled={busy} style={{ marginLeft: 4 }}>
          Clear
        </button>
      </div>
    </div>
  )
}

export default BulkActionBar
