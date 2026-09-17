import { useEffect, useState } from 'react'
import { api, type EmailServiceStatus } from '../api/client'

/**
 * Install/uninstall the email connector as a macOS LaunchAgent -- the
 * background-service alternative to `cd email_ingest && ./run.sh`, and a
 * close mirror of BotServiceControl.tsx (see that file for the fuller
 * reasoning, identical here). Once installed, launchd starts it at login
 * and restarts it if it ever crashes -- "running the connector" stops
 * being something the user has to remember, same as the Discord bot.
 *
 * Installing also creates the connector's Python environment the first
 * time, if it doesn't exist yet (see backend/app/service_venv.py) -- so
 * this button is genuinely the only step, no terminal required at all.
 *
 * Kept as its own component, same reasoning as BotServiceControl: it
 * polls its own status independently of EmailConnect's open/closed form
 * state, and the collapsed Settings row wants this too.
 */
function EmailServiceControl(): React.JSX.Element | null {
  const [status, setStatus] = useState<EmailServiceStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [busyLabel, setBusyLabel] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.emailService
      .status()
      .then(setStatus)
      .catch(() => setStatus(null))
  }, [])

  async function run(label: string, action: () => Promise<EmailServiceStatus>): Promise<void> {
    setBusy(true)
    setBusyLabel(label)
    setError(null)
    try {
      setStatus(await action())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
      setBusyLabel(null)
    }
  }

  // Not yet loaded, or a non-macOS build -- nothing useful to show. The
  // caller (EmailConnect) still offers the manual `./run.sh` path either way.
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
              onClick={() => run('Restarting…', api.emailService.restart)}
              disabled={busy}
            >
              {busyLabel === 'Restarting…' ? busyLabel : 'Restart'}
            </button>
            <button
              className="btn-ghost"
              style={{ padding: '6px 12px', fontSize: 12 }}
              onClick={() => run('Removing…', api.emailService.uninstall)}
              disabled={busy}
            >
              {busyLabel === 'Removing…' ? busyLabel : 'Uninstall service'}
            </button>
          </>
        ) : (
          <button
            className="btn-ghost"
            style={{ padding: '6px 12px', fontSize: 12 }}
            onClick={() => run('Setting up…', api.emailService.install)}
            disabled={busy}
          >
            {busyLabel === 'Setting up…' ? busyLabel : 'Install background service'}
          </button>
        )}
      </div>
      <div style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
        {busyLabel === 'Setting up…'
          ? 'Setting up the connector for the first time -- this can take a bit while its dependencies install.'
          : status.installed
            ? 'Starts automatically at login and restarts itself if it crashes -- you never have to run it by hand.'
            : 'Runs the connector in the background permanently, without a terminal window. Uninstall any time.'}
      </div>
      {error && <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{error}</div>}
    </div>
  )
}

export default EmailServiceControl
