import { useEffect, useState } from 'react'
import { api } from '../api/client'
import CatalogMatchReview from './CatalogMatchReview'

/**
 * Syncs the external product catalog (currently Pokemon + One Piece, via
 * the free tcgtracking.com API -- no key needed, see backend app/catalog.py
 * for why it was chosen over pokemontcg.io/TCGPlayer/PriceCharting) and
 * runs matching against your products. Exact matches apply themselves;
 * anything less certain lands in the review queue below.
 */
function CatalogMatchControl(): React.JSX.Element {
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [suggestionCount, setSuggestionCount] = useState(0)
  const [reviewOpen, setReviewOpen] = useState(false)

  useEffect(() => {
    refreshCount()
  }, [])

  async function refreshCount(): Promise<void> {
    try {
      setSuggestionCount((await api.catalog.suggestions()).length)
    } catch {
      setSuggestionCount(0)
    }
  }

  async function syncAndMatch(category: 'pokemon' | 'onepiece'): Promise<void> {
    setBusy(category)
    setMessage(null)
    try {
      const sync = await api.catalog.sync(category)
      const match = await api.catalog.match()
      setMessage(
        `Synced ${sync.products_upserted} products` +
          (sync.sets_failed ? ` (${sync.sets_failed} sets skipped, retriable)` : '') +
          ` · ${match.auto_confirmed} matched automatically, ${match.suggested} need a quick look`
      )
      await refreshCount()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Sync failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
        Fills in clean product names and icons by matching against a real card catalog. Exact matches apply
        automatically; anything uncertain goes to a quick review instead of guessing.
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={() => syncAndMatch('pokemon')} disabled={busy !== null}>
          {busy === 'pokemon' ? 'Syncing Pokémon…' : 'Sync Pokémon'}
        </button>
        <button className="btn-ghost" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={() => syncAndMatch('onepiece')} disabled={busy !== null}>
          {busy === 'onepiece' ? 'Syncing One Piece…' : 'Sync One Piece'}
        </button>
        {suggestionCount > 0 && (
          <button className="btn-primary" style={{ padding: '8px 14px', fontSize: 12.5 }} onClick={() => setReviewOpen(true)}>
            Review {suggestionCount} match{suggestionCount === 1 ? '' : 'es'}
          </button>
        )}
      </div>
      {message && <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{message}</div>}
      {reviewOpen && (
        <CatalogMatchReview
          onClose={() => setReviewOpen(false)}
          onChanged={refreshCount}
        />
      )}
    </div>
  )
}

export default CatalogMatchControl
