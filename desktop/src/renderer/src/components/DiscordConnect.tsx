import { useEffect, useState } from 'react'
import { api, type ChannelScope, type DiscordStatus, type SyncStatus } from '../api/client'
import BotServiceControl from './BotServiceControl'

interface DiscordConnectProps {
  status: DiscordStatus
  onUpdated: (status: DiscordStatus) => void
}

/** The "Connect Discord" form in Settings -- writes bot/.env through the
 * backend instead of the user hand-editing it. The form itself still
 * doesn't run the bot process (see backend/app/routers/discord.py's
 * docstring for why it stays separate from Cache); BotServiceControl below
 * is the part that actually keeps a bot process alive, via a macOS
 * LaunchAgent instead of a manually-run terminal. */
function DiscordConnect({ status, onUpdated }: DiscordConnectProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [token, setToken] = useState('')
  const [guildId, setGuildId] = useState(status.guild_id ?? '')
  const [scope, setScope] = useState<ChannelScope>(status.channel_scope ?? 'all')
  const [channelIds, setChannelIds] = useState(status.channel_ids ?? '')
  const [profileFilter, setProfileFilter] = useState(status.profile_filter ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sync, setSync] = useState<SyncStatus | null>(null)
  const [resyncing, setResyncing] = useState(false)

  useEffect(() => {
    api.sync.status().then(setSync).catch(() => setSync(null))
  }, [])

  async function requestResync(): Promise<void> {
    setResyncing(true)
    try {
      setSync(await api.sync.request(true))
    } finally {
      setResyncing(false)
    }
  }

  /** Most recent successful channel scan, or null if nothing has synced. */
  function lastSyncedLabel(): string {
    const stamps = (sync?.sources ?? [])
      .map((s) => s.last_synced_at)
      .filter((s): s is string => s != null)
      .sort()
    if (stamps.length === 0) return 'never synced'
    return `last synced ${new Date(stamps[stamps.length - 1]).toLocaleString()}`
  }

  function startEdit(): void {
    setToken('')
    setGuildId(status.guild_id ?? '')
    setScope(status.channel_scope ?? 'all')
    setChannelIds(status.channel_ids ?? '')
    setProfileFilter(status.profile_filter ?? '')
    setError(null)
    setJustSaved(false)
    setOpen(true)
  }

  async function save(): Promise<void> {
    setSaving(true)
    setError(null)
    try {
      const updated = await api.discord.configure({
        token: token || undefined,
        guild_id: guildId,
        channel_scope: scope,
        channel_ids: scope === 'specific' ? channelIds : undefined,
        profile_filter: profileFilter || undefined
      })
      onUpdated(updated)
      // If the background service is already installed, restart it so it
      // picks up the new token/scope immediately -- otherwise the
      // already-running bot keeps using the stale config until someone
      // happens to restart it by hand. Best-effort: not installed yet is
      // the common case (nothing to restart), so a failure here never
      // blocks the save itself from reading as successful -- the config
      // is saved either way.
      try {
        const serviceStatus = await api.botService.status()
        if (serviceStatus.installed) {
          await api.botService.restart()
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
        {/* Identity row: title + status pill on the left, the one primary
           action on the right. Kept to just these two things because this
           card is narrow (one cell of a 2x2 grid) -- Resync and the
           service control below each get their own full-width row instead
           of competing for space here. */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <span style={{ fontSize: 13, fontWeight: 500 }}>Discord bot</span>
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
          {status.configured
            ? `Server ${status.guild_id} · ${status.channel_scope === 'all' ? 'all channels' : `${status.channel_ids?.split(',').length ?? 0} channel(s)`}${status.profile_filter ? ` · filtering: ${status.profile_filter}` : ''}`
            : 'Not connected yet'}
        </div>

        {status.configured && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <span className="num" style={{ fontSize: 11, color: 'var(--text-faint)' }}>
              {sync?.pending ? 'Resync queued — the bot picks it up within ~20s' : lastSyncedLabel()}
            </span>
            <button
              className="btn-ghost"
              style={{ padding: '6px 12px', fontSize: 12, flexShrink: 0 }}
              onClick={requestResync}
              disabled={resyncing || sync?.pending}
              title="Re-read the whole channel history. Anything you deleted in Cache stays deleted."
            >
              {sync?.pending ? 'Queued…' : resyncing ? 'Requesting…' : 'Resync'}
            </button>
          </div>
        )}

        {status.configured && <BotServiceControl />}
      </div>
    )
  }

  return (
    <div style={{ borderTop: '1px solid var(--divider)', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontSize: 13, fontWeight: 500 }}>Connect Discord</div>

      {justSaved ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>
            Saved. The bot itself runs as its own process, separate from Cache, so it keeps logging checkouts even
            when Cache is closed.
          </div>
          <BotServiceControl />
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
              cd bot && ./run.sh
            </div>
          </details>
          <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5, alignSelf: 'flex-start' }} onClick={() => setOpen(false)}>
            Done
          </button>
        </div>
      ) : (
        <>
          <ConnectField label="Bot token" hint="Discord Developer Portal → your app → Bot → Reset Token">
            <input
              className="field-input"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={status.configured ? 'Leave blank to keep the current token' : 'Paste your bot token'}
            />
          </ConnectField>

          <ConnectField label="Server (guild) ID" hint="Enable Developer Mode, then right-click your server icon → Copy Server ID">
            <input className="field-input num" value={guildId} onChange={(e) => setGuildId(e.target.value)} placeholder="000000000000000000" />
          </ConnectField>

          <ConnectField label="Channels to watch" hint={null}>
            <div style={{ display: 'flex', gap: 6, background: 'var(--field-bg)', border: '1px solid var(--field-border)', borderRadius: 9, padding: 3 }}>
              {(['all', 'specific'] as ChannelScope[]).map((s) => (
                <button
                  key={s}
                  onClick={() => setScope(s)}
                  style={{
                    flex: 1,
                    padding: 8,
                    borderRadius: 7,
                    fontSize: 12,
                    fontWeight: 600,
                    border: 'none',
                    cursor: 'pointer',
                    background: scope === s ? 'var(--accent-gradient)' : 'transparent',
                    color: scope === s ? 'oklch(14% 0.01 255)' : 'var(--text-secondary)'
                  }}
                >
                  {s === 'all' ? 'All channels' : 'Specific channels'}
                </button>
              ))}
            </div>
          </ConnectField>

          {scope === 'specific' && (
            <ConnectField label="Channel IDs" hint="Right-click a channel → Copy Channel ID. Comma-separated for more than one.">
              <input className="field-input num" value={channelIds} onChange={(e) => setChannelIds(e.target.value)} placeholder="111111111, 222222222" />
            </ConnectField>
          )}

          <ConnectField label="Only my checkouts (optional)" hint="Case-insensitive, matches part of the profile name — e.g. 'eugene' matches 'eugene1'">
            <input className="field-input" value={profileFilter} onChange={(e) => setProfileFilter(e.target.value)} placeholder="Leave blank to log everyone's checkouts" />
          </ConnectField>

          {error && <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{error}</div>}

          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn-primary" style={{ flex: 1 }} onClick={save} disabled={saving || !guildId || (scope === 'specific' && !channelIds)}>
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

export default DiscordConnect
