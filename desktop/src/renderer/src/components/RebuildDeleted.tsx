import { useEffect, useState } from 'react'
import { api, type DeletedSummary } from '../api/client'

/**
 * Brings back orders the user deleted, re-created from the ingest payloads
 * Cache already stored.
 *
 * Deliberately NOT a "trash bin": deleted orders are really gone from the
 * Orders table, so there is no bin to browse and nothing hidden in the list
 * you're looking at. What survives is the record that the source ever sent
 * the checkout -- which is also what stops a Discord resync from silently
 * re-creating something you deleted. This is the one button that undoes that.
 *
 * Hides itself when there is nothing to bring back, so Settings doesn't
 * carry a permanently dead control.
 */
function RebuildDeleted(): React.JSX.Element | null {
  const [summary, setSummary] = useState<DeletedSummary | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    load()
  }, [])

  async function load(): Promise<void> {
    try {
      setSummary(await api.orders.deletedSummary())
    } catch {
      setSummary(null)
    }
  }

  async function rebuild(): Promise<void> {
    if (!summary) return
    if (
      !window.confirm(
        `Bring back ${summary.rebuildable} deleted order${summary.rebuildable === 1 ? '' : 's'}? ` +
          `They'll be re-created exactly as they were first recorded, along with any inventory they produced.`
      )
    )
      return
    setBusy(true)
    setMessage(null)
    try {
      const result = await api.orders.rebuild()
      setMessage(
        `Brought back ${result.rebuilt} order${result.rebuilt === 1 ? '' : 's'}` +
          (result.skipped ? ` · ${result.skipped} had nothing stored to rebuild from` : '')
      )
      await load()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Rebuild failed')
    } finally {
      setBusy(false)
    }
  }

  if (!summary || summary.dismissed === 0) return null

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        padding: '14px 0',
        borderTop: '1px solid var(--divider)'
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>Deleted orders</div>
        <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 2 }}>
          {message ??
            `${summary.rebuildable} of ${summary.dismissed} can be brought back from what Cache recorded — no Discord needed.`}
        </div>
      </div>
      <button
        className="btn-ghost"
        style={{ padding: '8px 14px', fontSize: 12.5, flexShrink: 0 }}
        onClick={rebuild}
        disabled={busy || summary.rebuildable === 0}
      >
        {busy ? 'Rebuilding…' : 'Rebuild'}
      </button>
    </div>
  )
}

export default RebuildDeleted
