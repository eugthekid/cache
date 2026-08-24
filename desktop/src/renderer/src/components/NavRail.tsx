import { useState } from 'react'

export type Screen = 'dashboard' | 'orders' | 'inventory' | 'settings'

interface NavRailProps {
  active: Screen
  onNavigate: (screen: Screen) => void
  userEmail: string
}

const COLLAPSE_KEY = 'cache_nav_collapsed'

function NavRail({ active, onNavigate, userEmail }: NavRailProps): React.JSX.Element {
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === 'true')

  function toggleCollapsed(): void {
    setCollapsed((prev) => {
      const next = !prev
      localStorage.setItem(COLLAPSE_KEY, String(next))
      return next
    })
  }

  return (
    <div className="nav-rail" style={{ width: collapsed ? 76 : 240, alignItems: collapsed ? 'center' : 'stretch' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: collapsed ? 0 : '0 6px', justifyContent: collapsed ? 'center' : 'flex-start' }}>
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
        {!collapsed && (
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600, letterSpacing: '-0.01em' }}>
            CACHE
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%' }}>
        <NavItem collapsed={collapsed} active={active === 'dashboard'} onClick={() => onNavigate('dashboard')} label="Dashboard">
          <svg width="17" height="17" viewBox="0 0 20 20" fill="none">
            <rect x="3" y="3" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
            <rect x="11" y="3" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
            <rect x="3" y="11" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
            <rect x="11" y="11" width="6" height="6" rx="1.5" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </NavItem>

        <NavItem collapsed={collapsed} active={active === 'orders'} onClick={() => onNavigate('orders')} label="Orders">
          <svg width="17" height="17" viewBox="0 0 20 20" fill="none">
            <path
              d="M5 3h7l3 3v11a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
            <path d="M7 9h6M7 12h6M7 15h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </NavItem>

        <NavItem collapsed={collapsed} active={active === 'inventory'} onClick={() => onNavigate('inventory')} label="Inventory">
          <svg width="17" height="17" viewBox="0 0 20 20" fill="none">
            <path d="M10 2 3 5.5 10 9l7-3.5L10 2Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
            <path
              d="M3 5.5V14l7 3.5 7-3.5V5.5M10 9v8.5"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
          </svg>
        </NavItem>

        <NavItem collapsed={collapsed} active={false} onClick={() => {}} label="Market" disabled badge="v2">
          <svg width="17" height="17" viewBox="0 0 20 20" fill="none">
            <path
              d="M3 14l4.5-5 3 3L17 5"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path d="M13 5h4v4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </NavItem>

        <NavItem collapsed={collapsed} active={active === 'settings'} onClick={() => onNavigate('settings')} label="Settings">
          <svg width="17" height="17" viewBox="0 0 20 20" fill="none">
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
        </NavItem>
      </div>

      <div
        style={{
          marginTop: 'auto',
          width: '100%',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          borderTop: '1px solid var(--divider)',
          paddingTop: 14
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, justifyContent: collapsed ? 'center' : 'flex-start' }}>
          <div
            style={{
              width: 24,
              height: 24,
              borderRadius: 7,
              background: 'linear-gradient(135deg, oklch(60% 0.1 215 / 0.55), oklch(55% 0.14 292 / 0.55))',
              color: 'oklch(95% 0.05 250)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 11.5,
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
              flexShrink: 0
            }}
          >
            {userEmail.charAt(0).toUpperCase()}
          </div>
          {!collapsed && (
            <div className="num" style={{ fontSize: 12.5, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {userEmail}
            </div>
          )}
        </div>

        <button
          onClick={toggleCollapsed}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: collapsed ? 'center' : 'flex-start',
            gap: 10,
            padding: collapsed ? '8px' : '8px 10px',
            borderRadius: 8,
            border: 'none',
            background: 'transparent',
            color: 'var(--text-faint)',
            cursor: 'pointer',
            width: '100%'
          }}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text-secondary)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-faint)')}
        >
          <svg width="15" height="15" viewBox="0 0 20 20" fill="none" style={{ transform: collapsed ? 'rotate(180deg)' : undefined, flexShrink: 0 }}>
            <path d="M12.5 4 6.5 10l6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M7 4v12" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" opacity="0.5" />
          </svg>
          {!collapsed && <span style={{ fontSize: 12 }}>Collapse</span>}
        </button>
      </div>
    </div>
  )
}

function NavItem({
  collapsed,
  active,
  onClick,
  label,
  children,
  disabled,
  badge
}: {
  collapsed: boolean
  active: boolean
  onClick: () => void
  label: string
  children: React.ReactNode
  disabled?: boolean
  badge?: string
}): React.JSX.Element {
  return (
    <button
      className={`navitem${active ? ' active' : ''}`}
      onClick={onClick}
      title={collapsed ? label : undefined}
      disabled={disabled}
      style={{
        cursor: disabled ? 'default' : 'pointer',
        opacity: disabled ? 0.55 : 1,
        justifyContent: collapsed ? 'center' : 'flex-start',
        padding: collapsed ? '11px 0' : '12px 14px',
        fontSize: 14.5,
        gap: 13
      }}
    >
      {children}
      {!collapsed && label}
      {!collapsed && badge && (
        <span className="pill pill-neutral" style={{ marginLeft: 'auto', padding: '2px 6px', fontSize: 9 }}>
          {badge}
        </span>
      )}
    </button>
  )
}

export default NavRail
