import { useEffect, useState } from 'react'
import { api, type CurrentUser, type InventorySummary } from './api'

type ConnectionState = 'connecting' | 'connected' | 'error'

function App(): React.JSX.Element {
  const [state, setState] = useState<ConnectionState>('connecting')
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [summary, setSummary] = useState<InventorySummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load(): Promise<void> {
      try {
        await api.health()
        const [meResult, summaryResult] = await Promise.all([api.me(), api.inventorySummary()])
        if (cancelled) return
        setUser(meResult)
        setSummary(summaryResult)
        setState('connected')
      } catch (err) {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
        setState('error')
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem', maxWidth: 480 }}>
      <h1>Inventory Tracker</h1>

      {state === 'connecting' && <p>Connecting to backend…</p>}

      {state === 'error' && (
        <div style={{ color: '#c0392b' }}>
          <p>
            <strong>Couldn't reach the backend.</strong>
          </p>
          <p>Make sure it's running: <code>cd backend && ./run.sh</code></p>
          <p style={{ fontSize: '0.85em', opacity: 0.7 }}>{error}</p>
        </div>
      )}

      {state === 'connected' && user && summary && (
        <div>
          <p style={{ color: '#27ae60' }}>✓ Connected as {user.email}</p>
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <tbody>
              <tr>
                <td>Total units tracked</td>
                <td>{summary.total_units}</td>
              </tr>
              <tr>
                <td>In hand</td>
                <td>{summary.in_hand}</td>
              </tr>
              <tr>
                <td>Listed</td>
                <td>{summary.listed}</td>
              </tr>
              <tr>
                <td>Sold</td>
                <td>{summary.sold}</td>
              </tr>
              <tr>
                <td>Total cost basis</td>
                <td>${summary.total_cost_basis.toFixed(2)}</td>
              </tr>
              <tr>
                <td>Total sold revenue</td>
                <td>${summary.total_sold_revenue.toFixed(2)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default App
