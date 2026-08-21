import EmptyState from './EmptyState'

interface ErrorStateProps {
  screenTitle: string
  message?: string | null
  onRetry: () => void
}

/** A per-screen data-load failure -- distinct from App.tsx's whole-app
 * "backend unreachable" gate, which only covers startup. This is for a
 * request that fails after the app is already up: same visual language
 * (red-tinted card, "offline" pill) so it never gets mistaken for "no
 * data", but scoped to the one screen whose fetch failed. */
function ErrorState({ screenTitle, message, onRetry }: ErrorStateProps): React.JSX.Element {
  return (
    <>
      <div className="screen-title">{screenTitle}</div>
      <div
        className="card"
        style={{
          flex: 1,
          minHeight: 0,
          padding: '18px 22px',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          borderColor: 'oklch(74% 0.19 25 / 0.3)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{screenTitle}</div>
          <span className="pill" style={{ background: 'oklch(74% 0.19 25 / 0.2)', color: 'oklch(82% 0.19 25)' }}>
            <span className="dot" />
            offline
          </span>
        </div>
        <div style={{ borderTop: '1px solid var(--divider)' }} />
        <EmptyState
          icon={
            <svg width="21" height="21" viewBox="0 0 20 20" fill="none">
              <path d="M10 3.5 18 17.5H2L10 3.5Z" stroke="oklch(84% 0.17 25)" strokeWidth="1.5" strokeLinejoin="round" />
              <path d="M10 8.5v3.6" stroke="oklch(84% 0.17 25)" strokeWidth="1.6" strokeLinecap="round" />
              <circle cx="10" cy="14.6" r="0.85" fill="oklch(84% 0.17 25)" />
            </svg>
          }
          iconBg="oklch(74% 0.19 25 / 0.14)"
          iconBorder="oklch(74% 0.19 25 / 0.3)"
          title="Can&rsquo;t reach the backend"
          body={message || 'Your data is safe on disk — the local server just isn’t responding.'}
          actions={
            <button className="btn-primary" style={{ padding: '8px 15px', fontSize: 12 }} onClick={onRetry}>
              Retry
            </button>
          }
        />
      </div>
    </>
  )
}

export default ErrorState
