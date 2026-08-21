export type Screen = 'dashboard' | 'orders' | 'inventory' | 'settings'

interface NavRailProps {
  active: Screen
  onNavigate: (screen: Screen) => void
  userEmail: string
}

function NavRail({ active, onNavigate, userEmail }: NavRailProps): React.JSX.Element {
  return (
    <div className="nav-rail">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0 6px' }}>
        <div className="logo-mark">
          <svg width="14" height="14" viewBox="0 0 20 20" fill="none">
            <path
              d="M10 2 3 5.5 10 9l7-3.5L10 2Z"
              stroke="oklch(14% 0.01 255)"
              strokeWidth="2"
              strokeLinejoin="round"
            />
          </svg>
        </div>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em' }}>
          CACHE
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        <button
          className={`navitem${active === 'dashboard' ? ' active' : ''}`}
          onClick={() => onNavigate('dashboard')}
        >
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
            <rect x="3" y="3" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
            <rect x="11" y="3" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
            <rect x="3" y="11" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
            <rect x="11" y="11" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
          </svg>
          Dashboard
        </button>

        <button className={`navitem${active === 'orders' ? ' active' : ''}`} onClick={() => onNavigate('orders')}>
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
            <path
              d="M5 3h7l3 3v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
            <path d="M7 9h6M7 12h6M7 15h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          Orders
        </button>

        <button
          className={`navitem${active === 'inventory' ? ' active' : ''}`}
          onClick={() => onNavigate('inventory')}
        >
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
            <path d="M10 2 3 5.5 10 9l7-3.5L10 2Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
            <path
              d="M3 5.5V14l7 3.5 7-3.5V5.5M10 9v8.5"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
          Inventory
        </button>

        <div className="navitem" style={{ cursor: 'default', opacity: 0.55 }}>
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
            <path
              d="M3 14l4.5-5 3 3L17 5"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path d="M13 5h4v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Market
          <span
            className="pill pill-neutral"
            style={{ marginLeft: 'auto', padding: '2px 6px', fontSize: 9 }}
          >
            v2
          </span>
        </div>

        <button
          className={`navitem${active === 'settings' ? ' active' : ''}`}
          onClick={() => onNavigate('settings')}
        >
          <svg width="16" height="16" viewBox="0 0 20 20" fill="none">
            <path d="M2 5h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="12" cy="5" r="1.7" stroke="currentColor" strokeWidth="1.6" />
            <path d="M15.5 5H18" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            <path d="M2 10h1.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="7" cy="10" r="1.7" stroke="currentColor" strokeWidth="1.6" />
            <path d="M10.5 10H18" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            <path d="M2 15h9.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            <circle cx="14" cy="15" r="1.7" stroke="currentColor" strokeWidth="1.6" />
            <path d="M17.5 15H18" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
          Settings
        </button>
      </div>

      <div
        style={{
          marginTop: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: 9,
          borderTop: '1px solid var(--divider)',
          paddingTop: 14
        }}
      >
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: 7,
            background: 'linear-gradient(135deg, oklch(60% 0.1 215 / 0.55), oklch(55% 0.14 292 / 0.55))',
            color: 'oklch(95% 0.05 250)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11,
            fontWeight: 700,
            fontFamily: 'var(--font-mono)'
          }}
        >
          {userEmail.charAt(0).toUpperCase()}
        </div>
        <div className="num" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          {userEmail}
        </div>
      </div>
    </div>
  )
}

export default NavRail
