import { useEffect, useRef, useState } from 'react'
import { api, type LicenseStatus, type Source } from '../api/client'

function Settings(): React.JSX.Element {
  const [license, setLicense] = useState<LicenseStatus | null>(null)
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(true)
  const [exportMessage, setExportMessage] = useState<string | null>(null)
  const [restoreMessage, setRestoreMessage] = useState<string | null>(null)
  const restoreInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    load()
  }, [])

  async function load(): Promise<void> {
    setLoading(true)
    try {
      const [licenseStatus, sourceList] = await Promise.all([api.license.status(), api.sources.list()])
      setLicense(licenseStatus)
      setSources(sourceList)
    } finally {
      setLoading(false)
    }
  }

  async function handleLogOut(): Promise<void> {
    if (!window.confirm('Log out? You’ll need your key (or trial mode) to get back in.')) return
    localStorage.removeItem('cache_trial_mode')
    try {
      // Harmless no-op if nothing was ever activated -- always safe to call.
      await api.license.deactivate()
    } finally {
      // A full reload, not a state reset: App's gate check runs once on
      // mount, and re-deriving that flow from a child screen would mean
      // either prop-drilling a "go back to activation" callback several
      // levels deep or standing up global state for something that only
      // happens once per app session. Reloading is what makes the exact
      // same startup gate logic run again from scratch, guaranteed.
      window.location.reload()
    }
  }

  async function handleExport(): Promise<void> {
    setExportMessage('Exporting…')
    try {
      const { blob, filename } = await api.backup.export()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
      setExportMessage(`Saved ${filename}.`)
    } catch (err) {
      setExportMessage(err instanceof Error ? err.message : 'Export failed.')
    }
  }

  async function handleRestoreFile(event: React.ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setRestoreMessage('Restoring…')
    try {
      const result = await api.backup.restore(file)
      setRestoreMessage(`Restored ${result.orders} orders and ${result.inventory_items} inventory items. Restart the app to finish.`)
    } catch (err) {
      setRestoreMessage(err instanceof Error ? err.message : 'Restore failed.')
    }
  }

  const discordSource = sources.find((s) => s.type === 'discord_channel')
  const trialMode = localStorage.getItem('cache_trial_mode') === 'true'

  if (loading) {
    return (
      <>
        <div className="screen-title">Settings</div>
        <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>Loading…</div>
      </>
    )
  }

  return (
    <>
      <div className="screen-title" style={{ position: 'relative' }}>
        Settings
      </div>

      <div style={{ position: 'relative', flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 760 }}>
        <div className="card" style={{ padding: '22px 26px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>License &amp; activation</div>
            <span className={`pill ${trialMode ? 'pill-neutral' : license?.activated ? 'pill-success' : 'pill-failed'}`}>
              <span className="dot" />
              {trialMode ? 'trial mode' : license?.activated ? 'activated' : 'not activated'}
            </span>
          </div>
          {license?.activated && (
            <SettingRow
              label="Activation key"
              sub={`CACH-••••-••••-${license.key_suffix ?? '••••'}`}
              action={null}
            />
          )}
          {license?.activated_at && (
            <SettingRow label="Activated" sub={new Date(license.activated_at).toLocaleDateString()} action={null} />
          )}
          {trialMode && <SettingRow label="Trial mode" sub="Capped at 25 tracked orders" action={null} />}
          <SettingRow
            label="Log out"
            sub="Back to the activation screen — your key still works to get back in"
            action={
              <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={handleLogOut}>
                Log out
              </button>
            }
          />
        </div>

        <div className="card" style={{ padding: '22px 26px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>Integrations</div>
          <SettingRow
            label="Discord bot"
            sub={discordSource ? discordSource.name : 'Not connected — run bot/run.sh with a real token'}
            action={
              <span className={`pill ${discordSource ? 'pill-success' : 'pill-neutral'}`}>
                <span className="dot" />
                {discordSource ? 'connected' : 'not connected'}
              </span>
            }
          />
          <SettingRow label="Email ingestion" sub="OAuth inbox scanning — not yet available" action={<span className="pill pill-neutral">coming soon</span>} dimmed />
        </div>

        <div className="card" style={{ padding: '22px 26px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 6 }}>Data &amp; storage</div>
          <SettingRow
            label="Database location"
            sub="~/Library/Application Support/inventory-tracker/app.db"
            action={null}
          />
          <SettingRow
            label="Import from spreadsheet"
            sub="Coming next — column mapping isn't wired up in the UI yet"
            action={<span className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5, opacity: 0.5, cursor: 'default' }}>Choose file</span>}
            dimmed
          />
          <SettingRow
            label="Export a backup"
            sub={exportMessage ?? 'Everything in one .cache file'}
            action={
              <button className="btn-primary" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={handleExport}>
                Export
              </button>
            }
          />
          <SettingRow
            label="Restore from a backup"
            sub={restoreMessage ?? 'Replaces everything with the backup’s contents'}
            action={
              <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={() => restoreInputRef.current?.click()}>
                Restore…
              </button>
            }
          />
          <input ref={restoreInputRef} type="file" accept=".cache" style={{ display: 'none' }} onChange={handleRestoreFile} />
        </div>

        <div className="card" style={{ padding: '22px 26px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Cache</div>
            <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 4 }}>
              v0.4.0 (MVP)
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

function SettingRow({
  label,
  sub,
  action,
  dimmed
}: {
  label: string
  sub: string
  action: React.ReactNode
  dimmed?: boolean
}): React.JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 20,
        padding: '16px 0',
        borderTop: '1px solid var(--divider)',
        opacity: dimmed ? 0.6 : 1
      }}
    >
      <div>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{label}</div>
        <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 2 }}>
          {sub}
        </div>
      </div>
      {action}
    </div>
  )
}

export default Settings
