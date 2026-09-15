import { useState } from 'react'
import { createPortal } from 'react-dom'
import { api, type ImportCommitResult, type ImportMode, type ImportPreview } from '../api/client'

type Step = 'upload' | 'map' | 'review'

interface ImportWizardProps {
  onClose: () => void
  onImported: () => void
}

const PURCHASE_FIELDS: { key: string; label: string }[] = [
  { key: 'product', label: 'Product' },
  { key: 'site', label: 'Site' },
  { key: 'price', label: 'Price' },
  { key: 'quantity', label: 'Quantity' },
  { key: 'order_date', label: 'Order date' },
  { key: 'status', label: 'Order status' },
  { key: 'category', label: 'Category' },
  { key: 'ship_to_label', label: 'Ship-to address' },
  { key: 'order_number', label: 'Order number' }
]

const UNIT_FIELDS: { key: string; label: string }[] = [
  { key: 'product', label: 'Product' },
  { key: 'price', label: 'Cost basis' },
  { key: 'quantity', label: 'Quantity' },
  { key: 'status', label: 'Status' },
  { key: 'notes', label: 'Notes' }
]

function ImportWizard({ onClose, onImported }: ImportWizardProps): React.JSX.Element {
  const [step, setStep] = useState<Step>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<ImportMode>('purchase')
  const [sheet, setSheet] = useState<string | undefined>(undefined)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<Record<string, string | null>>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [committing, setCommitting] = useState(false)
  const [result, setResult] = useState<ImportCommitResult | null>(null)

  const fields = mode === 'purchase' ? PURCHASE_FIELDS : UNIT_FIELDS

  async function runPreview(nextFile: File, nextMode: ImportMode, nextSheet?: string, nextMapping?: Record<string, string | null>): Promise<void> {
    setLoading(true)
    setError(null)
    try {
      const result = await api.import.preview(nextFile, { mode: nextMode, sheet: nextSheet, mapping: nextMapping })
      setPreview(result)
      setMapping(result.mapping)
      setSheet(result.sheet ?? undefined)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not read that file.')
    } finally {
      setLoading(false)
    }
  }

  async function handleFileChosen(event: React.ChangeEvent<HTMLInputElement>): Promise<void> {
    const chosen = event.target.files?.[0]
    if (!chosen) return
    setFile(chosen)
    await runPreview(chosen, mode)
    setStep('map')
  }

  async function changeMode(nextMode: ImportMode): Promise<void> {
    setMode(nextMode)
    if (file) await runPreview(file, nextMode, sheet)
  }

  async function changeSheet(nextSheet: string): Promise<void> {
    if (file) await runPreview(file, mode, nextSheet)
  }

  async function changeMapping(field: string, column: string | null): Promise<void> {
    const nextMapping = { ...mapping, [field]: column }
    setMapping(nextMapping)
    if (file) await runPreview(file, mode, sheet, nextMapping)
  }

  async function goToReview(): Promise<void> {
    setStep('review')
  }

  async function handleCommit(): Promise<void> {
    if (!file) return
    setCommitting(true)
    setError(null)
    try {
      const commitResult = await api.import.commit(file, { mode, sheet, mapping })
      setResult(commitResult)
      onImported()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed.')
    } finally {
      setCommitting(false)
    }
  }

  // Portaled to document.body: this can be opened from screens like
  // Settings, where it would otherwise render inside a .card that has
  // backdrop-filter (see global.css) -- which the CSS spec says makes
  // that card the containing block for "fixed" descendants instead of
  // the viewport. See CatalogMatchReview.tsx for the concrete bug this
  // caused there (opened off-screen, scrolled with the settings page).
  return createPortal(
    <div style={{ position: 'fixed', inset: 0, zIndex: 50, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ position: 'absolute', inset: 0, background: 'oklch(12% 0.012 260)', opacity: 0.7 }} onClick={result ? undefined : onClose} />
      <div className="card" style={{ position: 'relative', width: 900, maxHeight: '85vh', display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRadius: 16 }}>
        <div style={{ padding: '22px 28px 0', display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
            <div>
              <div style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 700 }}>Import from spreadsheet</div>
              <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 4 }}>
                Bring in existing inventory from Excel or CSV. Nothing is saved until you confirm.
              </div>
            </div>
            <button onClick={onClose} className="link-action" aria-label="Close" style={{ fontSize: 18, marginTop: 2 }}>
              ×
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <StepIndicator label="Upload file" active={step === 'upload'} done={step !== 'upload'} />
            <StepDivider />
            <StepIndicator label="Map columns" active={step === 'map'} done={step === 'review'} />
            <StepDivider />
            <StepIndicator label="Review & import" active={step === 'review'} done={false} />
          </div>
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: '18px 28px 24px' }}>
          {error && (
            <div style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--status-failed-bg)', color: 'var(--status-failed)', fontSize: 12.5, marginBottom: 14 }}>
              {error}
            </div>
          )}

          {step === 'upload' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 18, alignItems: 'center', padding: '30px 0' }}>
              <div style={{ display: 'flex', gap: 6, background: 'var(--field-bg)', border: '1px solid var(--field-border)', borderRadius: 9, padding: 3 }}>
                {(['purchase', 'unit'] as ImportMode[]).map((m) => (
                  <button
                    key={m}
                    onClick={() => setMode(m)}
                    style={{
                      padding: '8px 16px',
                      borderRadius: 7,
                      fontSize: 12.5,
                      fontWeight: 600,
                      border: 'none',
                      cursor: 'pointer',
                      background: mode === m ? 'var(--accent-gradient)' : 'transparent',
                      color: mode === m ? 'oklch(14% 0.01 255)' : 'var(--text-secondary)'
                    }}
                  >
                    {m === 'purchase' ? 'A purchase' : 'A unit I hold'}
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-faint)', textAlign: 'center', maxWidth: 420 }}>
                {mode === 'purchase'
                  ? 'Each row becomes an order, and successful orders spawn one inventory unit per quantity.'
                  : 'Each row becomes inventory directly — no purchase record, just what you hold and what it cost.'}
              </div>
              <label className="btn-primary" style={{ padding: '12px 24px', cursor: loading ? 'default' : 'pointer' }}>
                {loading ? 'Reading file…' : 'Choose a file'}
                <input type="file" accept=".xlsx,.csv" style={{ display: 'none' }} onChange={handleFileChosen} disabled={loading} />
              </label>
            </div>
          )}

          {step === 'map' && preview && (
            <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 24 }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div className="label">Import each row as</div>
                <div style={{ display: 'flex', gap: 6, background: 'var(--field-bg)', border: '1px solid var(--field-border)', borderRadius: 9, padding: 3 }}>
                  {(['purchase', 'unit'] as ImportMode[]).map((m) => (
                    <button
                      key={m}
                      onClick={() => changeMode(m)}
                      style={{
                        flex: 1,
                        padding: 7,
                        borderRadius: 7,
                        fontSize: 12,
                        fontWeight: 600,
                        border: 'none',
                        cursor: 'pointer',
                        background: mode === m ? 'var(--accent-gradient)' : 'transparent',
                        color: mode === m ? 'oklch(14% 0.01 255)' : 'var(--text-secondary)'
                      }}
                    >
                      {m === 'purchase' ? 'A purchase' : 'A unit I hold'}
                    </button>
                  ))}
                </div>

                {preview.sheet_names.length > 1 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div className="field-label">Sheet</div>
                    <select className="select" value={sheet ?? ''} onChange={(e) => changeSheet(e.target.value)}>
                      {preview.sheet_names.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                <div className="label" style={{ marginTop: 4 }}>
                  Column mapping
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {fields.map((f) => (
                    <div key={f.key} style={{ display: 'grid', gridTemplateColumns: '1fr 16px 1.2fr', alignItems: 'center', gap: 8, padding: '5px 0' }}>
                      <div className="num" style={{ fontSize: 11.5, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {f.label}
                      </div>
                      <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>→</span>
                      <select className="select" style={{ fontSize: 12 }} value={mapping[f.key] ?? ''} onChange={(e) => changeMapping(f.key, e.target.value || null)}>
                        <option value="">Don&rsquo;t import</option>
                        {preview.columns.map((col) => (
                          <option key={col} value={col}>
                            {col}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>Preview</div>
                  <div style={{ display: 'flex', gap: 7 }}>
                    <span className="pill pill-success">{preview.ready} ready</span>
                    {preview.duplicates > 0 && <span className="pill pill-neutral">{preview.duplicates} duplicate</span>}
                    {preview.needs_attention > 0 && <span className="pill pill-warn">{preview.needs_attention} need attention</span>}
                  </div>
                </div>
                <PreviewTable preview={preview} loading={loading} />
              </div>
            </div>
          )}

          {step === 'review' && preview && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {result ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: '40px 0' }}>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>Imported</div>
                  <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                    {result.created_orders > 0 && `${result.created_orders} orders · `}
                    {result.created_inventory_items} inventory units created.
                  </div>
                  {(result.catalog_matched > 0 || result.catalog_merged > 0 || result.catalog_suggested > 0) && (
                    <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
                      {result.catalog_matched > 0 && `${result.catalog_matched} matched to the catalog`}
                      {result.catalog_matched > 0 && result.catalog_merged > 0 && ' · '}
                      {result.catalog_merged > 0 && `${result.catalog_merged} merged into existing products`}
                      {(result.catalog_matched > 0 || result.catalog_merged > 0) && result.catalog_suggested > 0 && ' · '}
                      {result.catalog_suggested > 0 && `${result.catalog_suggested} need a quick review in Settings`}
                    </div>
                  )}
                  <button className="btn-primary" onClick={onClose} style={{ marginTop: 10 }}>
                    Done
                  </button>
                </div>
              ) : (
                <>
                  <PreviewTable preview={preview} loading={false} />
                  <div style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
                    Rows needing attention are skipped unless you go back and fix the mapping.
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {!result && (
          <div style={{ borderTop: '1px solid var(--divider)', padding: '16px 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'oklch(21% 0.015 255 / 0.5)' }}>
            <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)' }}>
              {preview ? `${preview.row_count} rows in file` : ''}
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              {step === 'map' && (
                <>
                  <button className="btn-ghost" onClick={() => setStep('upload')} style={{ padding: '10px 18px' }}>
                    Back
                  </button>
                  <button className="btn-primary" onClick={goToReview} disabled={!preview || preview.ready === 0} style={{ padding: '10px 20px' }}>
                    Review {preview?.ready ?? 0} rows
                  </button>
                </>
              )}
              {step === 'review' && (
                <>
                  <button className="btn-ghost" onClick={() => setStep('map')} style={{ padding: '10px 18px' }}>
                    Back
                  </button>
                  <button className="btn-primary" onClick={handleCommit} disabled={committing || !preview || preview.ready === 0} style={{ padding: '10px 20px' }}>
                    {committing ? 'IMPORTING…' : `IMPORT ${preview?.ready ?? 0} ${mode === 'purchase' ? 'ORDERS' : 'UNITS'}`}
                  </button>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  )
}

function StepIndicator({ label, active, done }: { label: string; active: boolean; done: boolean }): React.JSX.Element {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, fontWeight: 600, color: active ? 'var(--text-primary)' : done ? 'var(--status-success)' : 'var(--text-faint)' }}>
      <span
        style={{
          width: 20,
          height: 20,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          background: active ? 'var(--accent-gradient)' : done ? 'var(--status-success-bg)' : 'oklch(28% 0.014 255)',
          color: active ? 'oklch(14% 0.01 255)' : done ? 'var(--status-success)' : 'var(--text-faint)'
        }}
      >
        {done ? '✓' : ''}
      </span>
      {label}
    </div>
  )
}

function StepDivider(): React.JSX.Element {
  return <div style={{ flex: '0 0 28px', height: 1, background: 'var(--divider)' }} />
}

function PreviewTable({ preview, loading }: { preview: ImportPreview; loading: boolean }): React.JSX.Element {
  return (
    <div className="card" style={{ padding: '4px 12px', maxHeight: 360, overflow: 'auto', opacity: loading ? 0.5 : 1 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ paddingTop: 12, width: 32 }}>Row</th>
            <th style={{ paddingTop: 12 }}>Product</th>
            <th style={{ paddingTop: 12 }}>Site</th>
            <th style={{ paddingTop: 12 }}>Status / issue</th>
          </tr>
        </thead>
        <tbody>
          {preview.rows.map((row) => (
            <tr key={row.row_number} style={{ background: row.duplicate ? 'oklch(28% 0.012 255 / 0.4)' : !row.ok ? 'oklch(30% 0.06 85 / 0.35)' : undefined }}>
              <td className="num" style={{ color: 'var(--text-faint)' }}>
                {row.row_number}
              </td>
              <td style={{ textDecoration: row.duplicate ? 'line-through' : undefined, opacity: row.duplicate ? 0.6 : 1 }}>
                {String(row.fields.product ?? row.fields.raw_product_text ?? row.fields.product_text ?? '—')}
              </td>
              <td style={{ color: 'var(--text-secondary)' }}>{String(row.fields.site ?? '—')}</td>
              <td>
                {row.duplicate ? (
                  <span className="pill pill-neutral">already tracked</span>
                ) : row.ok ? (
                  <span className="pill pill-success">ready</span>
                ) : (
                  <span className="pill pill-warn">{row.reason}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default ImportWizard
