import { useEffect, useState } from 'react'
import { api, type BotServiceStatus } from '../api/client'

/**
 * Install/uninstall the Discord bot as a macOS LaunchAgent -- the
 * background-service alternative to `cd bot && ./run.sh`. Once installed,
 * launchd starts the bot at login and restarts it if it ever crashes, so
 * "running the bot" stops being something the user has to remember.
 *
 * Kept as its own component (rather than folded into DiscordConnect)
 * because it polls its own status independently of the connect form's
 * open/closed state -- the collapsed Settings row wants this too.
 */
function BotServiceControl(): React.JSX.Element | null {
  const [status, setStatus] = useState<BotServiceStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.botService
      .status()
      .then(setStatus)
      .catch(() => setStatus(null))
  }, [])

  async function run(action: () => Promise<BotServiceStatus>): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      setStatus(await action())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  // Not yet loaded, or a non-macOS build -- nothing useful to show. The
  // caller (Settings) still offers the manual `./run.sh` path either way.
  if (!status || !status.supported) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className={`pill ${status.installed && status.running ? 'pill-success' : 'pill-neutral'}`}>
          <span className="dot" />
          {status.installed ? (status.running ? 'running in background' : 'installed, not running') : 'not installed'}
        </span>
        {status.installed ? (
          <>
            <button
              className="btn-ghost"
              style={{ padding: '6px 12px', fontSize: 12 }}
              onClick={() => run(api.botService.restart)}
              disabled={busy}
            >
              Restart
            </button>
            <button
              className="btn-ghost"
              style={{ padding: '6px 12px', fontSize: 12 }}
              onClick={() => run(api.botService.uninstall)}
              disabled={busy}
            >
              Uninstall service
            </button>
          </>
        ) : (
          <button
            className="btn-ghost"
            style={{ padding: '6px 12px', fontSize: 12 }}
            onClick={() => run(api.botService.install)}
            disabled={busy}
          >
            {busy ? 'Installing…' : 'Install background service'}
          </button>
        )}
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
        {status.installed
          ? 'Starts automatically at login and restarts itself if it crashes -- you never have to run it by hand.'
          : 'Runs the bot in the background permanently, without a terminal window. Uninstall any time.'}
      </div>
      {error && <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{error}</div>}
    </div>
  )
}

export default BotServiceControl
