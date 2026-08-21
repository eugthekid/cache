import { useEffect, useState } from 'react'
import { api } from './api/client'
import Activation from './screens/Activation'
import Dashboard from './screens/Dashboard'
import Orders from './screens/Orders'
import Inventory from './screens/Inventory'
import Settings from './screens/Settings'
import NavRail, { type Screen } from './components/NavRail'
import WavyBackground from './components/WavyBackground'

type GateState = 'checking' | 'needs-activation' | 'unreachable' | 'ready'

function App(): React.JSX.Element {
  const [gate, setGate] = useState<GateState>('checking')
  const [screen, setScreen] = useState<Screen>('dashboard')
  const [userEmail, setUserEmail] = useState('')

  useEffect(() => {
    checkGate()
  }, [])

  async function checkGate(): Promise<void> {
    setGate('checking')
    try {
      await api.health()
      const me = await api.me()
      setUserEmail(me.email)

      if (localStorage.getItem('cache_trial_mode') === 'true') {
        setGate('ready')
        return
      }
      const license = await api.license.status()
      setGate(license.activated ? 'ready' : 'needs-activation')
    } catch {
      setGate('unreachable')
    }
  }

  if (gate === 'checking') {
    return (
      <div style={{ width: '100vw', height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-faint)' }}>
        Connecting…
      </div>
    )
  }

  if (gate === 'unreachable') {
    return (
      <div style={{ width: '100vw', height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="card" style={{ padding: '28px 32px', maxWidth: 420, textAlign: 'center', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 700 }}>Can&rsquo;t reach the backend</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            Your data is safe on disk — the local server just isn&rsquo;t responding.
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
            Make sure it&rsquo;s running: <code>cd backend && ./run.sh</code>
          </div>
          <button className="btn-primary" onClick={checkGate} style={{ marginTop: 6 }}>
            Retry
          </button>
        </div>
      </div>
    )
  }

  if (gate === 'needs-activation') {
    return <Activation onActivated={checkGate} />
  }

  return (
    <div className="app-shell">
      <NavRail active={screen} onNavigate={setScreen} userEmail={userEmail} />
      <div className="main-content">
        <WavyBackground />
        {screen === 'dashboard' && <Dashboard />}
        {screen === 'orders' && <Orders />}
        {screen === 'inventory' && <Inventory />}
        {screen === 'settings' && <Settings />}
      </div>
    </div>
  )
}

export default App
