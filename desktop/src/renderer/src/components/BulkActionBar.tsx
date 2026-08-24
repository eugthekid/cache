import { useState } from 'react'

interface BulkActionBarProps<S extends string> {
  count: number
  statusOptions: S[]
  onSetStatus: (status: S) => Promise<void>
  onDelete: () => Promise<void>
  onClear: () => void
  noun: string
}

/** The row that appears above a table once one or more checkboxes are
 * checked -- shared by Orders and Inventory since both need the same two
 * actions (set a status across the selection, or delete it). Kept generic
 * over the status union so each screen still gets its own real status
 * type in the dropdown, not a loose string. */
function BulkActionBar<S extends string>({
  count,
  statusOptions,
  onSetStatus,
  onDelete,
  onClear,
  noun
}: BulkActionBarProps<S>): React.JSX.Element {
  const [status, setStatus] = useState<S>(statusOptions[0])
  const [busy, setBusy] = useState(false)

  async function applyStatus(): Promise<void> {
    setBusy(true)
    try {
      await onSetStatus(status)
    } finally {
      setBusy(false)
    }
  }

  async function handleDelete(): Promise<void> {
    if (!window.confirm(`Delete ${count} ${noun}${count === 1 ? '' : 's'}? A Discord resync won't bring them back.`)) return
    setBusy(true)
    try {
      await onDelete()
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
