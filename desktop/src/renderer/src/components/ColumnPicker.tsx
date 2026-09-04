import { useEffect, useRef, useState } from 'react'

interface ColumnPickerProps {
  /** Every column that CAN be shown, in table order. */
  options: { key: string; label: string }[]
  visible: Set<string>
  onChange: (next: Set<string>) => void
  onReset: () => void
}

/**
 * Dropdown checklist for choosing which table columns to show.
 *
 * Not a portal (unlike ImportWizard/CatalogMatchReview): this anchors to
 * its own button rather than centring on the viewport, so it wants to be
 * positioned relative to that button, and an absolutely-positioned child
 * is not affected by the backdrop-filter containing-block problem those
 * two hit -- only `position: fixed` is.
 */
function ColumnPicker({ options, visible, onChange, onReset }: ColumnPickerProps): React.JSX.Element {
  const [open, setOpen] = useState(false)
  const wrapper = useRef<HTMLDivElement>(null)

  // Click-outside to dismiss. Listening on the document (not a backdrop
  // element) keeps the rest of the toolbar clickable while it's open.
  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent): void {
      if (!wrapper.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  function toggle(key: string): void {
    const next = new Set(visible)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    onChange(next)
  }

  return (
    <div ref={wrapper} style={{ position: 'relative' }}>
      <button
        className="field-input"
        onClick={() => setOpen((v) => !v)}
        style={{
          width: 'auto', height: 30, padding: '0 12px', fontSize: 12,
          cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6
        }}
      >
        Columns
        <span style={{ fontSize: 9, opacity: 0.7 }}>▼</span>
      </button>

      {open && (
        <div
          className="card"
          style={{
            position: 'absolute', top: 'calc(100% + 6px)', right: 0, zIndex: 30,
            width: 210, padding: '10px 6px 8px', borderRadius: 10,
            maxHeight: 340, overflow: 'auto'
          }}
        >
          {options.map((opt) => (
            <label
              key={opt.key}
              style={{
                display: 'flex', alignItems: 'center', gap: 9,
                padding: '6px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 12.5
              }}
            >
              <input type="checkbox" checked={visible.has(opt.key)} onChange={() => toggle(opt.key)} />
              {opt.label}
            </label>
          ))}
          <div style={{ borderTop: '1px solid var(--divider)', margin: '6px 10px 0', paddingTop: 7 }}>
            <button className="link-action" onClick={onReset} style={{ fontSize: 11.5 }}>
              Reset to default
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default ColumnPicker
