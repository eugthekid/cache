import { useRef, useState } from 'react'
import { api } from '../api/client'
import WavyBackground from '../components/WavyBackground'

interface ActivationProps {
  onActivated: () => void
}

const BLOCK_COUNT = 4
const BLOCK_LEN = 4

function Activation({ onActivated }: ActivationProps): React.JSX.Element {
  const [blocks, setBlocks] = useState<string[]>(Array(BLOCK_COUNT).fill(''))
  const [activating, setActivating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [restoreMessage, setRestoreMessage] = useState<string | null>(null)
  const inputsRef = useRef<(HTMLInputElement | null)[]>([])
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const key = blocks.join('-')

  function setBlock(index: number, value: string): void {
    const cleaned = value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, BLOCK_LEN)
    setBlocks((prev) => {
      const next = [...prev]
      next[index] = cleaned
      return next
    })
    if (cleaned.length === BLOCK_LEN && index < BLOCK_COUNT - 1) {
      inputsRef.current[index + 1]?.focus()
    }
  }

  function handlePaste(index: number, event: React.ClipboardEvent<HTMLInputElement>): void {
    const pasted = event.clipboardData.getData('text').toUpperCase().replace(/[^A-Z0-9]/g, '')
    if (pasted.length <= BLOCK_LEN) return // let the default single-block paste happen
    event.preventDefault()
    const chunks = pasted.match(new RegExp(`.{1,${BLOCK_LEN}}`, 'g')) ?? []
    setBlocks((prev) => {
      const next = [...prev]
      for (let i = 0; i < BLOCK_COUNT; i++) {
        if (chunks[i]) next[index + i < BLOCK_COUNT ? index + i : i] = chunks[i].slice(0, BLOCK_LEN)
      }
      return next.map((b) => b.slice(0, BLOCK_LEN))
    })
  }

  function handleKeyDown(index: number, event: React.KeyboardEvent<HTMLInputElement>): void {
    if (event.key === 'Backspace' && blocks[index] === '' && index > 0) {
      inputsRef.current[index - 1]?.focus()
    }
  }

  async function activate(): Promise<void> {
    setActivating(true)
    setError(null)
    try {
      await api.license.activate(key)
      onActivated()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setActivating(false)
    }
  }

  function tryWithoutKey(): void {
    localStorage.setItem('cache_trial_mode', 'true')
    onActivated()
  }

  async function handleRestoreFile(event: React.ChangeEvent<HTMLInputElement>): Promise<void> {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setRestoreMessage('Restoring…')
    try {
      const result = await api.backup.restore(file)
      setRestoreMessage(
        `Restored ${result.orders} orders and ${result.inventory_items} inventory items. Restart the app to finish.`
      )
    } catch (err) {
      setRestoreMessage(err instanceof Error ? err.message : 'Restore failed.')
    }
  }

  const allFilled = blocks.every((b) => b.length === BLOCK_LEN)

  return (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        background: 'var(--bg)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        overflow: 'hidden'
      }}
    >
      <WavyBackground />
      <div
        style={{
          position: 'absolute',
          top: -120,
          left: '50%',
          marginLeft: -330,
          width: 660,
          height: 520,
          background: 'radial-gradient(ellipse, oklch(62% 0.15 255 / 0.2), transparent 70%)',
          filter: 'blur(12px)',
          pointerEvents: 'none'
        }}
      />

      <div
        className="card"
        style={{
          position: 'relative',
          width: 540,
          padding: '44px 46px 30px',
          display: 'flex',
          flexDirection: 'column',
          gap: 26,
          borderRadius: 20
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 13, textAlign: 'center' }}>
          <div
            className="logo-mark"
            style={{ width: 60, height: 60, borderRadius: 18, boxShadow: '0 0 34px -4px oklch(70% 0.15 240 / 0.75)' }}
          >
            <svg width="30" height="30" viewBox="0 0 20 20" fill="none">
              <path
                d="M10 2 3 5.5 10 9l7-3.5L10 2Z"
                stroke="oklch(14% 0.01 255)"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
              <path
                d="M3 5.5V14l7 3.5 7-3.5V5.5M10 9v8.5"
                stroke="oklch(14% 0.01 255)"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 25, fontWeight: 700, letterSpacing: '-0.015em' }}>
            Cache
          </div>
          <div style={{ fontSize: 13.5, color: 'var(--text-secondary)', lineHeight: 1.55, maxWidth: 370 }}>
            Enter your activation key to unlock the app. Everything stays on this machine — no account, no sign-in.
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
          <div style={{ display: 'flex', gap: 9, alignItems: 'center' }}>
            {blocks.map((value, i) => (
              <div key={i} style={{ display: 'contents' }}>
                <input
                  ref={(el) => {
                    inputsRef.current[i] = el
                  }}
                  className="field-input"
                  value={value}
                  onChange={(e) => setBlock(i, e.target.value)}
                  onKeyDown={(e) => handleKeyDown(i, e)}
                  onPaste={(e) => handlePaste(i, e)}
                  maxLength={BLOCK_LEN}
                  autoFocus={i === 0}
                  style={{
                    flex: 1,
                    textAlign: 'center',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 17,
                    fontWeight: 600,
                    letterSpacing: '0.13em',
                    padding: '13px 6px'
                  }}
                />
                {i < BLOCK_COUNT - 1 && <span style={{ color: 'var(--text-faint)', fontSize: 15 }}>–</span>}
              </div>
            ))}
          </div>
          {error && (
            <div style={{ fontSize: 12, color: 'var(--status-failed)' }}>{error}</div>
          )}
        </div>

        <button className="btn-primary" style={{ width: '100%', padding: 13 }} disabled={!allFilled || activating} onClick={activate}>
          {activating ? 'ACTIVATING…' : 'ACTIVATE'}
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 13 }}>
          <div style={{ flex: 1, height: 1, background: 'var(--divider)' }} />
          <span className="label">or</span>
          <div style={{ flex: 1, height: 1, background: 'var(--divider)' }} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <button
            className="btn-ghost"
            style={{ display: 'flex', alignItems: 'center', gap: 13, padding: '14px 16px', justifyContent: 'flex-start' }}
            onClick={() => fileInputRef.current?.click()}
          >
            <svg width="19" height="19" viewBox="0 0 20 20" fill="none" style={{ flexShrink: 0 }}>
              <path
                d="M10 13V3.5M6.3 9.3 10 13l3.7-3.7"
                stroke="var(--accent-cyan)"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M3.5 13.5v2.2a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-2.2"
                stroke="var(--accent-cyan)"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
            <div style={{ textAlign: 'left' }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Restore from a backup</div>
              <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', fontWeight: 400 }}>
                Moving from another machine? Bring everything across.
              </div>
            </div>
          </button>
          <input ref={fileInputRef} type="file" accept=".cache" style={{ display: 'none' }} onChange={handleRestoreFile} />
          {restoreMessage && <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{restoreMessage}</div>}

          <button
            className="btn-ghost"
            style={{ display: 'flex', alignItems: 'center', gap: 13, padding: '14px 16px', justifyContent: 'flex-start' }}
            onClick={tryWithoutKey}
          >
            <svg width="19" height="19" viewBox="0 0 20 20" fill="none" style={{ flexShrink: 0 }}>
              <circle cx="10" cy="10" r="7.5" stroke="var(--text-secondary)" strokeWidth="1.6" />
              <path
                d="M7.3 10.2 9.2 12l3.6-4"
                stroke="var(--text-secondary)"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <div style={{ textAlign: 'left' }}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>Try it without a key</div>
              <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', fontWeight: 400 }}>
                Full app, capped at 25 tracked orders.
              </div>
            </div>
          </button>
        </div>
      </div>
    </div>
  )
}

export default Activation
