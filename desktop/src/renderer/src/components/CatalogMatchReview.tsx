import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, type CatalogCandidate, type CatalogSuggestion } from '../api/client'

/**
 * Reviews catalog-name suggestions one at a time.
 *
 * Every suggestion here is ALREADY below the auto-confirm bar (see
 * backend app/catalog.py) -- an exact normalized match never reaches this
 * queue at all, it's applied automatically. What lands here is either a
 * fuzzy guess worth a human glance, or a genuinely ambiguous SKU (a
 * "Styles May Vary" tin that could be any of several catalog products
 * until the box is opened) where "candidates" lets the user pick the
 * right one instead of accepting a single guess.
 */
function CatalogMatchReview({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }): React.JSX.Element {
  const [suggestions, setSuggestions] = useState<CatalogSuggestion[]>([])
  const [loading, setLoading] = useState(true)
  const [index, setIndex] = useState(0)
  const [candidates, setCandidates] = useState<CatalogCandidate[] | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.catalog
      .suggestions()
      .then(setSuggestions)
      .finally(() => setLoading(false))
  }, [])

  const current = suggestions[index]

  async function loadCandidates(): Promise<void> {
    if (!current) return
    setCandidates(null)
    setCandidates(await api.catalog.candidates(current.product_id))
  }

  function advance(): void {
    setCandidates(null)
    if (index + 1 < suggestions.length) {
      setIndex(index + 1)
    } else {
      onChanged()
      onClose()
    }
  }

  async function confirm(catalogProductId: string): Promise<void> {
    if (!current) return
    setBusy(true)
    try {
      await api.catalog.confirm(current.product_id, catalogProductId)
      advance()
    } finally {
      setBusy(false)
    }
  }

  async function reject(): Promise<void> {
    if (!current) return
    setBusy(true)
    try {
      await api.catalog.reject(current.product_id)
      advance()
    } finally {
      setBusy(false)
    }
  }

  // Portaled to document.body: this is invoked from inside the "Product
  // matching" settings card, and that card's backdrop-filter (see
  // global.css's .card rule) makes it establish its OWN containing block
  // for fixed-position descendants -- the CSS spec's rule for filter,
  // backdrop-filter, transform, and perspective. Without the portal this
  // "fixed" overlay is fixed to the CARD, not the viewport, so it renders
  // whatever the card's scroll position happens to be -- reproduced as
  // opening far down the page, mostly off-screen, exactly like this.
  return createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'oklch(10% 0.01 255 / 0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 50
      }}
      onClick={onClose}
    >
      <div
        className="card"
        style={{ width: 560, maxHeight: '80vh', overflow: 'auto', padding: 26, display: 'flex', flexDirection: 'column', gap: 16 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>Review product matches</div>
          <button className="btn-ghost" style={{ padding: '6px 12px', fontSize: 12 }} onClick={onClose}>
            Close
          </button>
        </div>

        {loading ? (
          <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>Loading…</div>
        ) : suggestions.length === 0 ? (
          <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>
            Nothing to review right now. Run "Sync + match" again after your next sync.
          </div>
        ) : !current ? (
          <div style={{ color: 'var(--text-faint)', fontSize: 13 }}>All done.</div>
        ) : (
          <>
            <div className="num" style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
              {index + 1} of {suggestions.length}
            </div>

            <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Your product</div>
            <div style={{ fontSize: 14, fontWeight: 500 }}>{current.our_name}</div>

            {!candidates ? (
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', padding: '10px 0' }}>
                {current.candidate_image_url && (
                  <img
                    src={current.candidate_image_url}
                    alt=""
                    style={{ width: 56, height: 56, objectFit: 'contain', borderRadius: 8, background: 'var(--field-bg)' }}
                  />
                )}
                <div>
                  <div style={{ fontSize: 14 }}>{current.candidate_name}</div>
                  {current.candidate_set && (
                    <div className="num" style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
                      {current.candidate_set}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 280, overflow: 'auto' }}>
                {candidates.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => confirm(c.id)}
                    disabled={busy}
                    style={{
                      display: 'flex', gap: 12, alignItems: 'center', padding: 10, borderRadius: 8,
                      background: 'var(--field-bg)', border: '1px solid var(--field-border)', cursor: 'pointer', textAlign: 'left'
                    }}
                  >
                    {c.image_url && (
                      <img src={c.image_url} alt="" style={{ width: 40, height: 40, objectFit: 'contain', borderRadius: 6 }} />
                    )}
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 13 }}>{c.name}</div>
                      <div className="num" style={{ fontSize: 11, color: 'var(--text-faint)' }}>
                        {c.set_name} · match {Math.round(c.score * 100)}%
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
              {!candidates && (
                <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={loadCandidates} disabled={busy}>
                  See other options
                </button>
              )}
              <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={reject} disabled={busy}>
                Not a match
              </button>
              {!candidates && (
                <button
                  className="btn-primary"
                  style={{ padding: '8px 14px', fontSize: 12.5 }}
                  onClick={() => confirm(current.candidate_id)}
                  disabled={busy}
                >
                  Confirm
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>,
    document.body
  )
}

export default CatalogMatchReview
