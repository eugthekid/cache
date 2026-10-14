import { useEffect, useState } from 'react'
import { api, type FamilyDashboardData, type FamilyVariant, type ProductFields, type ProductGroup, type VariantKind } from '../api/client'
import { getVariantsLayout } from '../preferences'
import ItemDetails from './ItemDetails'
import { RetailerBadge, retailerColor } from './retailerBrand'

interface Props {
  familyId: string
  group: ProductGroup
  categories: string[]
  onBack: () => void
  /** Open one variant's own screen (counts, sales, moving units). */
  onOpenVariant: (productId: string, editCounts?: boolean) => void
  /** Called after anything that changes the list, so it isn't left stale. */
  onChanged: () => void
}

function money(n: number): string {
  return `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function signedMoney(n: number): string {
  return `${n >= 0 ? '+' : '-'}${money(n)}`
}

function profitColor(profit: number | null): string {
  return profit == null ? 'var(--text-faint)' : profit >= 0 ? 'var(--status-success)' : 'var(--status-failed)'
}

function KindBadge({ kind, inline }: { kind: VariantKind; inline?: boolean }): React.JSX.Element | null {
  if (!kind) return null
  return (
    <span
      style={{
        marginLeft: inline ? 8 : 0,
        flex: 'none',
        whiteSpace: 'nowrap',
        padding: '1px 7px',
        borderRadius: 999,
        fontSize: 10.5,
        fontWeight: 600,
        background: kind === 'random' ? 'var(--status-warn-bg)' : 'var(--status-neutral-bg)',
        color: kind === 'random' ? 'var(--status-warn)' : 'var(--text-secondary)'
      }}
    >
      {kind === 'random' ? 'Random' : 'Specific'}
    </span>
  )
}

/** The text a variant is called, without the "Random · " prefix (the badge says it). */
function shortLabel(v: FamilyVariant): string {
  return v.label.replace(/^Random · /, '')
}

function Tile({ size, url }: { size: number; url: string | null }): React.JSX.Element {
  const box: React.CSSProperties = { width: size, height: size, borderRadius: Math.round(size / 5), background: 'var(--field-bg)', flex: 'none' }
  return url ? <img src={url} alt="" style={{ ...box, objectFit: 'contain' }} /> : <div style={box} />
}

/**
 * A variant's picture. A specific variant shows its own. A random one could be
 * any of the variants it names, so it shows those overlapped; failing that, its
 * own listing photo, then a "?".
 */
function VariantImage({ v, size }: { v: FamilyVariant; size: number }): React.JSX.Element {
  if (v.variant_kind === 'random') {
    const urls = v.option_image_urls.slice(0, 2)
    if (urls.length >= 2) {
      const small = Math.round(size * 0.74)
      const piece: React.CSSProperties = { position: 'absolute', width: small, height: small, objectFit: 'contain', borderRadius: 6, background: 'var(--field-bg)', border: '1px solid var(--divider)' }
      return (
        <div style={{ position: 'relative', width: size, height: size, flex: 'none' }}>
          <img src={urls[0]} alt="" style={{ ...piece, left: 0, top: 0 }} />
          <img src={urls[1]} alt="" style={{ ...piece, right: 0, bottom: 0 }} />
        </div>
      )
    }
    if (urls.length === 1) return <Tile size={size} url={urls[0]} />
    if (!v.image_url) {
      return (
        <div style={{ width: size, height: size, borderRadius: Math.round(size / 5), background: 'var(--field-bg)', flex: 'none', display: 'grid', placeItems: 'center', color: 'var(--text-faint)', fontWeight: 600, fontSize: size / 2.4 }}>
          ?
        </div>
      )
    }
  }
  return <Tile size={size} url={v.image_url} />
}

function EditCountsButton({ onClick }: { onClick: () => void }): React.JSX.Element {
  return (
    <button
      className="link-action"
      style={{ fontSize: 11.5, justifySelf: 'end', whiteSpace: 'nowrap' }}
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
    >
      Edit counts
    </button>
  )
}

const COLS = 'minmax(120px, 2.2fr) repeat(4, 44px) 60px 70px 72px 84px'

function StatCell({ label, value, color }: { label: string; value: React.ReactNode; color?: string }): React.JSX.Element {
  return (
    <div>
      <div className="field-label">{label}</div>
      <div className="num" style={{ fontSize: 14, fontWeight: 500, marginTop: 2, color }}>
        {value}
      </div>
    </div>
  )
}

function VariantTable({ variants, onOpen }: { variants: FamilyVariant[]; onOpen: (id: string, editCounts?: boolean) => void }): React.JSX.Element {
  return (
    <div style={{ minWidth: 620 }}>
      <div className="field-label" style={{ display: 'grid', gridTemplateColumns: COLS, gap: 8, paddingBottom: 6, whiteSpace: 'nowrap' }}>
        <span>Variant</span>
        <span style={{ textAlign: 'right' }}>Units</span>
        <span style={{ textAlign: 'right' }}>Placed</span>
        <span style={{ textAlign: 'right' }}>Transit</span>
        <span style={{ textAlign: 'right' }}>In hand</span>
        <span style={{ textAlign: 'right' }}>Sold</span>
        <span style={{ textAlign: 'right' }}>Avg cost</span>
        <span style={{ textAlign: 'right' }}>Profit</span>
        <span />
      </div>
      {variants.map((v) => (
        <div
          key={v.product_id}
          className="row"
          onClick={() => onOpen(v.product_id)}
          style={{ display: 'grid', gridTemplateColumns: COLS, gap: 8, alignItems: 'center', padding: '7px 0', borderTop: '1px solid var(--divider)', fontSize: 12.5, cursor: 'pointer' }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }} title={v.name}>
            <VariantImage v={v} size={34} />
            <span style={{ minWidth: 0, display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 3 }}>
              <span style={{ maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{shortLabel(v)}</span>
              <KindBadge kind={v.variant_kind} />
            </span>
          </span>
          <span className="num" style={{ textAlign: 'right', fontWeight: 600 }}>{v.units}</span>
          <span className="num" style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>{v.order_placed}</span>
          <span className="num" style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>{v.in_transit}</span>
          <span className="num" style={{ textAlign: 'right', color: 'var(--status-success)' }}>{v.in_hand}</span>
          <span className="num" style={{ textAlign: 'right', color: 'var(--text-secondary)' }}>{v.sold}</span>
          <span className="num" style={{ textAlign: 'right' }}>{v.avg_cost != null ? money(v.avg_cost) : '—'}</span>
          <span className="num" style={{ textAlign: 'right', color: profitColor(v.profit) }}>{v.profit != null ? signedMoney(v.profit) : '—'}</span>
          <EditCountsButton onClick={() => onOpen(v.product_id, true)} />
        </div>
      ))}
    </div>
  )
}

function VariantCards({ variants, onOpen }: { variants: FamilyVariant[]; onOpen: (id: string, editCounts?: boolean) => void }): React.JSX.Element {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 12 }}>
      {variants.map((v) => (
        <div
          key={v.product_id}
          className="row"
          onClick={() => onOpen(v.product_id)}
          style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '12px 14px', borderRadius: 12, background: 'var(--field-bg)', cursor: 'pointer' }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }} title={v.name}>
            <VariantImage v={v} size={52} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{shortLabel(v)}</div>
              <div style={{ marginTop: 3 }}>
                <KindBadge kind={v.variant_kind} />
              </div>
            </div>
            <div style={{ marginLeft: 'auto', textAlign: 'right', flex: 'none' }}>
              <div className="num" style={{ fontSize: 20, fontWeight: 500 }}>{v.units}</div>
              <div className="num" style={{ fontSize: 11, color: profitColor(v.profit) }}>
                {v.profit != null ? signedMoney(v.profit) : 'no sales'}
              </div>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8 }}>
            <StatCell label="In hand" value={v.in_hand} color="var(--status-success)" />
            <StatCell label="Transit" value={v.in_transit} />
            <StatCell label="Sold" value={v.sold} />
            <StatCell label="Avg cost" value={v.avg_cost != null ? money(v.avg_cost) : '—'} />
          </div>
          <div>
            <EditCountsButton onClick={() => onOpen(v.product_id, true)} />
          </div>
        </div>
      ))}
    </div>
  )
}

function VariantSplit({ variants, onOpen }: { variants: FamilyVariant[]; onOpen: (id: string, editCounts?: boolean) => void }): React.JSX.Element {
  const [picked, setPicked] = useState(variants[0]?.product_id ?? '')
  const v = variants.find((x) => x.product_id === picked) ?? variants[0]
  if (!v) return <div />
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) 1.4fr', gap: 16 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {variants.map((x) => (
          <div
            key={x.product_id}
            className="row"
            onClick={() => setPicked(x.product_id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '7px 10px',
              borderRadius: 10,
              cursor: 'pointer',
              background: x.product_id === v.product_id ? 'var(--field-bg)' : 'transparent',
              fontSize: 12.5
            }}
          >
            <VariantImage v={x} size={30} />
            <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{shortLabel(x)}</span>
            <span className="num" style={{ fontWeight: 600 }}>{x.units}</span>
          </div>
        ))}
      </div>
      <div style={{ background: 'var(--field-bg)', borderRadius: 12, padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <VariantImage v={v} size={64} />
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>
              {shortLabel(v)}
              <KindBadge kind={v.variant_kind} inline />
            </div>
            <div className="num" style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 3 }}>{v.name}</div>
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 12 }}>
          <StatCell label="Units" value={v.units} />
          <StatCell label="Placed" value={v.order_placed} />
          <StatCell label="Transit" value={v.in_transit} />
          <StatCell label="In hand" value={v.in_hand} color="var(--status-success)" />
          <StatCell label="Sold" value={v.sold} />
          <StatCell label="Avg cost" value={v.avg_cost != null ? money(v.avg_cost) : '—'} />
          <StatCell label="Avg sale" value={v.avg_sale_price != null ? money(v.avg_sale_price) : '—'} />
          <StatCell label="Profit" value={v.profit != null ? signedMoney(v.profit) : '—'} color={profitColor(v.profit)} />
        </div>
        <div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn-ghost" style={{ padding: '6px 14px', fontSize: 12 }} onClick={() => onOpen(v.product_id)}>
              Open {shortLabel(v)}
            </button>
            <button className="btn-ghost" style={{ padding: '6px 14px', fontSize: 12 }} onClick={() => onOpen(v.product_id, true)}>
              Edit counts
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * One item that comes in several variants -- the tech stickers as Lucario,
 * Alolan Exeggutor, or a random pick of either. Shows the whole item's
 * totals, then each variant with its own picture, counts, cost and profit.
 * Click a variant to open its own screen, where counts are edited, sales are
 * recorded (costed at THAT variant's average), and random units are moved to
 * the variant they turned out to be.
 *
 * Everything fits one screen: the summary is a single strip, and only the
 * variant list scrolls (inside its own card) if there are a great many.
 * Variants are grouped automatically, so there is nothing to add or remove
 * here -- only "Ungroup" if a grouping is wrong.
 */
function FamilyDashboard({ familyId, group, categories, onBack, onOpenVariant, onChanged }: Props): React.JSX.Element {
  const [data, setData] = useState<FamilyDashboardData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [renaming, setRenaming] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [layout] = useState(getVariantsLayout)

  useEffect(() => {
    let live = true
    api.families
      .dashboard(familyId)
      .then((d) => live && setData(d))
      .catch((err) => live && setError(err instanceof Error ? err.message : 'Failed to load this item'))
    return () => {
      live = false
    }
  }, [familyId])

  if (error && !data) {
    return (
      <div style={{ padding: 20 }}>
        <button className="btn-ghost" style={{ padding: '6px 12px', fontSize: 12 }} onClick={onBack}>
          ← Back
        </button>
        <div style={{ marginTop: 16, fontSize: 13, color: 'var(--status-failed)' }}>{error}</div>
      </div>
    )
  }
  if (!data) return <div style={{ padding: 20, fontSize: 13, color: 'var(--text-faint)' }}>Loading…</div>

  async function run(action: () => Promise<FamilyDashboardData>): Promise<void> {
    setBusy(true)
    setError(null)
    try {
      setData(await action())
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'That didn’t save')
    } finally {
      setBusy(false)
    }
  }

  function saveDetails(fields: ProductFields): void {
    run(() =>
      api.families.update(familyId, {
        ...(fields.product_type !== undefined && { product_type: fields.product_type }),
        ...(fields.category !== undefined && { category: fields.category })
      })
    )
  }

  async function saveName(): Promise<void> {
    setRenaming(false)
    const name = nameDraft.trim()
    if (name && name !== data!.name) await run(() => api.families.update(familyId, { name }))
  }

  async function ungroup(): Promise<void> {
    if (!window.confirm(`Ungroup "${data!.name}"? Each variant goes back to being its own item and stays that way. Nothing is deleted.`)) return
    setBusy(true)
    try {
      await api.families.ungroup(familyId)
      onChanged()
      onBack()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to ungroup')
      setBusy(false)
    }
  }

  const d = data
  const segments = [
    { label: 'Order placed', value: d.order_placed, color: 'var(--text-faint)' },
    { label: 'In transit', value: d.in_transit, color: 'var(--accent-cyan)' },
    { label: 'In hand', value: d.in_hand, color: 'var(--status-success)' },
    { label: 'Sold', value: d.sold, color: 'var(--accent-violet)' }
  ]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: '4px 4px 16px', height: '100%', minHeight: 0, overflowY: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button className="btn-ghost" style={{ padding: '6px 12px', fontSize: 12 }} onClick={onBack}>
          ← Back
        </button>
        <Tile size={36} url={group.image_url} />
        <div style={{ flex: 1, minWidth: 0 }}>
          {renaming ? (
            <input
              className="field-input"
              autoFocus
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={saveName}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveName()
                if (e.key === 'Escape') setRenaming(false)
              }}
              style={{ fontSize: 14, fontWeight: 600, height: 30 }}
            />
          ) : (
            <div
              style={{ fontSize: 14, fontWeight: 600, cursor: 'text', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              title="Double-click to rename"
              onDoubleClick={() => {
                setNameDraft(d.name)
                setRenaming(true)
              }}
            >
              {d.name}
            </div>
          )}
          {(d.set_name || d.series_name) && (
            <div style={{ fontSize: 11.5, color: 'var(--text-secondary)' }}>
              {[d.series_name, d.set_name].filter(Boolean).join(' · ')}
            </div>
          )}
          <div className="num" style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
            {d.variants.length} variants · {d.total_units} units
            {d.avg_cost != null && ` · avg cost ${money(d.avg_cost)}`}
            {` · ${money(d.invested)} invested`}
          </div>
        </div>
        {error && <span style={{ fontSize: 12, color: 'var(--status-failed)' }}>{error}</span>}
        <button className="link-action" style={{ fontSize: 11.5 }} onClick={ungroup} disabled={busy}>
          Ungroup
        </button>
      </div>

      <ItemDetails productType={d.product_type} category={d.category} categories={categories} onChange={saveDetails} />

      <div>
        <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', background: 'var(--field-bg)' }}>
          {segments.map((s) => (
            <div key={s.label} style={{ width: `${d.total_units ? (s.value / d.total_units) * 100 : 0}%`, background: s.color }} title={`${s.label} ${s.value}`} />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap', marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
          {segments.map((s) => (
            <span key={s.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: s.color }} />
              {s.label}
              <span className="num" style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>{s.value}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="card" style={{ padding: '14px 18px', flex: 'none' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 8 }}>
          <div style={{ fontSize: 13.5, fontWeight: 600 }}>Variants</div>
          <div style={{ fontSize: 11.5, color: 'var(--text-faint)' }}>
            Click a variant to edit counts, record a sale, or move random units to the variant you got
          </div>
        </div>
        <div style={{ overflowX: 'auto' }}>
          {layout === 'cards' ? (
            <VariantCards variants={d.variants} onOpen={onOpenVariant} />
          ) : layout === 'split' ? (
            <VariantSplit variants={d.variants} onOpen={onOpenVariant} />
          ) : (
            <VariantTable variants={d.variants} onOpen={onOpenVariant} />
          )}
        </div>
      </div>

      {d.retailers.length > 0 && (
        <div style={{ flex: 'none' }}>
          <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 8 }}>By retailer</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12 }}>
            {d.retailers.map((r) => (
              <div key={r.retailer} className="card" style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <RetailerBadge name={r.retailer} size={28} />
                  <div style={{ fontSize: 15, fontWeight: 600, color: retailerColor(r.retailer) ?? undefined, flex: 1, minWidth: 0 }}>{r.retailer}</div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="num" style={{ fontSize: 26, fontWeight: 500, lineHeight: 1 }}>{r.units}</div>
                    <div className="field-label" style={{ marginTop: 3 }}>units{r.avg_unit_price != null && ` · ${money(r.avg_unit_price)} each`}</div>
                  </div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10, paddingTop: 12, borderTop: '1px solid var(--divider)' }}>
                  {[
                    ['Order placed', r.order_placed, undefined],
                    ['In transit', r.in_transit, undefined],
                    ['In hand / sold', r.in_hand_or_sold, 'var(--status-success)']
                  ].map(([label, n, color]) => (
                    <div key={label as string}>
                      <div className="num" style={{ fontSize: 22, fontWeight: 500, color: color as string | undefined }}>{n as number}</div>
                      <div className="field-label" style={{ marginTop: 2 }}>{label as string}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default FamilyDashboard
