import { useState } from 'react'
import { api, type EmailStatus } from '../api/client'
import EmailServiceControl from './EmailServiceControl'

interface EmailConnectProps {
  status: EmailStatus
  onUpdated: (status: EmailStatus) => void
}

/** The "Connect Email" form in Settings -- writes email.env through the
 * backend instead of the user hand-editing it, mirroring DiscordConnect's
 * exact shape (see backend/app/routers/email_account.py's docstring for
 * why). EmailServiceControl below is this integration's BotServiceControl
 * equivalent -- installs the connector as a background service so nobody
 * has to run it by hand. */
function EmailConnect({ status, onUpdated }: EmailConnectProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [address, setAddress] = useState(status.address ?? '')
  const [appPassword, setAppPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function startEdit(): void {
    setAddress(status.address ?? '')
    setAppPassword('')
    setError(null)
    setJustSaved(false)
    setOpen(true)
  }

  async function save(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      const updated = await api.email.configure({
        address,
        app_password: appPassword || undefined
      })
      onUpdated(updated)
      // If the background service is already installed, restart it so it
      // picks up the new address/password immediately -- otherwise the
      // already-running process keeps using the stale credential until
      // someone happens to restart it by hand. Best-effort: not installed
      // yet is the common case (nothing to restart), so a failure here
      // never blocks the save itself from reading as successful -- the
      // credential is saved either way.
      try {
        const serviceStatus = await api.emailService.status()
        if (serviceStatus.installed) {
          await api.emailService.restart()
        }
      } catch {
        // Ignored -- see comment above.
      }
      setJustSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
          padding: '16px 0',
          borderTop: '1px solid var(--divider)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>Email</span>
            <span className={`pill ${status.configured ? 'pill-success' : 'pill-neutral'}`}>
              <span className="dot" />
              {status.configured ? 'configured' : 'not connected'}
            </span>
          </div>
          <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5, flexShrink: 0 }} onClick={startEdit}>
            {status.configured ? 'Edit' : 'Connect'}
          </button>
        </div>

        <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)' }}>
          {status.configured ? status.address : 'Not connected yet'}
        </div>

        {status.configured && <EmailServiceControl />}
      </div>
    )
  }

  return (
    <div style={{ borderTop: '1px solid var(--divider)', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 500 }}>Connect email</div>

      {justSaved ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
            Saved. Install the background service below to start reading confirmation, tracking, and cancellation
            emails automatically -- it runs on its own, even when Cache is closed.
          </div>
          <EmailServiceControl />
          <details>
            <summary style={{ fontSize: 11.5, color: 'var(--text-faint)', cursor: 'pointer' }}>
              Prefer to run it yourself?
            </summary>
            <div
              className="num"
              style={{
                fontSize: 12,
                marginTop: 8,
                padding: '10px 12px',
                background: 'var(--field-bg)',
                border: '1px solid var(--field-border)',
                borderRadius: 8
              }}
            >
              cd email_ingest && ./run.sh
            </div>
          </details>
          <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5, alignSelf: 'flex-start' }} onClick={() => setOpen(false)}>
            Done
          </button>
        </div>
      ) : (
        <>
          <ConnectField label="Email address" hint={null}>
            <input
              className="field-input"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="you@gmail.com"
            />
          </ConnectField>

          <ConnectField label="App password" hint="Google Account → Security → 2-Step Verification → App passwords. Not your regular password.">
            <input
              className="field-input"
              type="password"
              value={appPassword}
              onChange={(e) => setAppPassword(e.target.value)}
              placeholder={status.configured ? 'Leave blank to keep the current password' : 'Paste your app password'}
            />
          </ConnectField>

          {error && <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{error}</div>}

          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn-primary" style={{ flex: 1 }} onClick={save} disabled={saving || !address}>
              {saving ? 'SAVING…' : 'SAVE'}
            </button>
            <button className="btn-ghost" style={{ flex: 1 }} onClick={() => setOpen(false)} disabled={saving}>
              CANCEL
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function ConnectField({ label, hint, children }: { label: string; hint: string | null; children: React.ReactNode }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <div className="field-label">{label}</div>
      {children}
      {hint && (
        <div className="num" style={{ fontSize: 10.5, color: 'var(--text-faint)' }}>
          {hint}
        </div>
      )}
    </div>
  )
}

export default EmailConnect
