/** One shimmering placeholder box -- the raw primitive every skeleton
 * below composes. See .skel / @keyframes skel-shimmer in global.css. */
export function Skel({ style }: { style?: React.CSSProperties }): React.JSX.Element {
  return <div className="skel" style={style} />
}

/** Fading a couple of trailing rows (instead of every row at full
 * strength) is what makes a skeleton read as "content trailing off the
 * bottom of an unknown-length list" rather than a fixed table -- lifted
 * directly from the design canvas's loading mockup. */
const ROW_OPACITIES = [1, 1, 1, 0.6, 0.3]

/** A table-shaped skeleton: `widths` gives each column's relative flex
 * basis, left to right. Reused by Orders and Inventory, whose real
 * tables have different column counts. */
export function TableSkeleton({ rows = 5, widths }: { rows?: number; widths: number[] }): React.JSX.Element {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-evenly', padding: '4px 0' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 14, opacity: ROW_OPACITIES[i] ?? 0.3 }}>
          {widths.map((w, j) => (
            <Skel key={j} style={{ flex: w, height: 13 }} />
          ))}
        </div>
      ))}
    </div>
  )
}
