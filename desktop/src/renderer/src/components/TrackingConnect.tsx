import { useState } from 'react'
import { api, type TrackingStatus } from '../api/client'

interface TrackingConnectProps {
  status: TrackingStatus
  onUpdated: (status: TrackingStatus) => void
}

/** The "Connect tracking" form in Settings -- writes tracking.env through
 * the backend, mirroring EmailConnect's exact shape: a background thread
 * inside the backend (see backend/app/tracking_poller.py), not a
 * separate installed service. Saving starts it immediately. 17TRACK is
 * free at this app's scale (100 registrations/month, unlimited re-checks
 * after) -- see backend/app/tracking.py for why it was chosen and how a
 * future switch would work. */
function TrackingConnect({ status, onUpdated }: TrackingConnectProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function startEdit(): void {
    setApiKey('')
    setError(null)
    setJustSaved(false)
    setOpen(true)
  }

  async function save(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      const updated = await api.tracking.configure({ api_key: apiKey })
      onUpdated(updated)
      setJustSaved(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  async function disconnect(): Promise<void> {
    setSaving(true)
    try {
      const updated = await api.tracking.disconnect()
      onUpdated(updated)
      setOpen(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to disconnect')
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
            <span style={{ fontSize: 13, fontWeight: 500 }}>Live tracking</span>
            <span className={`pill ${status.polling ? 'pill-success' : 'pill-neutral'}`}>
              <span className="dot" />
              {status.polling ? 'watching shipments' : status.configured ? 'configured' : 'not connected'}
            </span>
          </div>
          <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5, flexShrink: 0 }} onClick={startEdit}>
            {status.configured ? 'Edit' : 'Connect'}
          </button>
        </div>

        <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)' }}>
          {status.configured ? `17TRACK · key ending ${status.api_key_suffix}` : 'Not connected yet'}
        </div>
      </div>
    )
  }

  return (
    <div style={{ borderTop: '1px solid var(--divider)', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 500 }}>Connect live tracking</div>

      {justSaved ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
            Saved. Cache checks the carrier&rsquo;s own status every 30 minutes for anything currently shipping, and
            notifies you when it&rsquo;s out for delivery or delivered.
          </div>
          <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5, alignSelf: 'flex-start' }} onClick={() => setOpen(false)}>
            Done
          </button>
        </div>
      ) : (
        <>
          <ConnectField
            label="17TRACK API key"
            hint="Free at 17track.net -- create an account, then Settings -> Security to generate a key. 100 shipments/month at no cost."
          >
            <input
              className="field-input"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={status.configured ? 'Leave blank to keep the current key' : 'Paste your API key'}
            />
          </ConnectField>

          {error && <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{error}</div>}

          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn-primary" style={{ flex: 1 }} onClick={save} disabled={saving || !apiKey}>
              {saving ? 'SAVING…' : 'SAVE'}
            </button>
            <button className="btn-ghost" style={{ flex: 1 }} onClick={() => setOpen(false)} disabled={saving}>
              CANCEL
            </button>
          </div>

          {status.configured && (
            <button
              className="link-action"
              style={{ fontSize: 11.5, color: 'var(--status-failed)', alignSelf: 'flex-start' }}
              onClick={disconnect}
              disabled={saving}
            >
              Disconnect
            </button>
          )}
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

export default TrackingConnect
