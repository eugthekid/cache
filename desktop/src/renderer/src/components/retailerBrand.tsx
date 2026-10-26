/**
 * A little mark and a text color per retailer, so the cards on the product
 * screen are easy to tell apart at a glance.
 *
 * The marks are simplified shapes drawn in each store's colors, not the
 * official artwork, and the colors are lightened where needed to read on the
 * dark theme. To use real logo files instead, swap the `mark` for an <img>.
 * A retailer with no entry gets a neutral badge with its initial.
 */

interface Brand {
  /** Text color, tuned for the dark theme. */
  color: string
  mark: (size: number) => React.JSX.Element
}

/** Matches however the name is written: "Pokémon Center", "pokemon center". */
function brandKey(name: string): string {
  return name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z]/g, '')
}

const svg = (size: number, children: React.ReactNode): React.JSX.Element => (
  <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ flex: 'none' }}>
    {children}
  </svg>
)

const BRANDS: Record<string, Brand> = {
  pokemoncenter: {
    color: '#FFCB05',
    mark: (size) =>
      svg(
        size,
        <>
          <circle cx="12" cy="12" r="11" fill="#FFFFFF" />
          <path d="M1 12a11 11 0 0 1 22 0z" fill="#EE1515" />
          <rect x="1" y="11" width="22" height="2.2" fill="#222222" />
          <circle cx="12" cy="12" r="3.6" fill="#FFFFFF" stroke="#222222" strokeWidth="2" />
        </>
      )
  },
  target: {
    color: '#FF5A5A',
    mark: (size) =>
      svg(
        size,
        <>
          <circle cx="12" cy="12" r="11" fill="#CC0000" />
          <circle cx="12" cy="12" r="7" fill="#FFFFFF" />
          <circle cx="12" cy="12" r="3.6" fill="#CC0000" />
        </>
      )
  },
  zumiez: {
    color: '#E6E6E6',
    mark: (size) =>
      svg(
        size,
        <>
          <rect x="1" y="1" width="22" height="22" rx="5" fill="#111111" />
          <path d="M7 7h10v2.2L10 15h7v2H7v-2.2L14 9H7z" fill="#FFFFFF" />
        </>
      )
  },
  walmart: {
    color: '#4FB0FF',
    mark: (size) =>
      svg(
        size,
        <>
          <rect x="1" y="1" width="22" height="22" rx="6" fill="#0071CE" />
          <g stroke="#FFC220" strokeWidth="3" strokeLinecap="round">
            {[0, 60, 120, 180, 240, 300].map((deg) => (
              <line key={deg} x1="12" y1="4.5" x2="12" y2="8.5" transform={`rotate(${deg} 12 12)`} />
            ))}
          </g>
        </>
      )
  },
  crunchyroll: {
    color: '#FF8A3D',
    mark: (size) =>
      svg(
        size,
        <>
          <circle cx="12" cy="12" r="11" fill="#F47521" />
          <circle cx="12" cy="12" r="6.5" fill="#FFFFFF" />
          <circle cx="14.2" cy="12" r="5" fill="#F47521" />
        </>
      )
  },
  bestbuy: {
    color: '#7B9BFF',
    mark: (size) =>
      svg(
        size,
        <>
          <rect x="1" y="4.5" width="22" height="15" rx="3" fill="#FFE000" />
          <circle cx="6" cy="12" r="1.7" fill="#0046BE" />
          <rect x="10" y="9" width="10" height="6" rx="1.2" fill="#0046BE" />
        </>
      )
  },
  menards: {
    color: '#3FBF6E',
    mark: (size) =>
      svg(
        size,
        <>
          <rect x="1" y="1" width="22" height="22" rx="6" fill="#1B8A3F" />
          <text x="12" y="17.5" textAnchor="middle" fontSize="15" fontWeight="700" fill="#FFFFFF" fontFamily="system-ui, sans-serif">
            M
          </text>
        </>
      )
  },
  samsclub: {
    color: '#5BB6F0',
    mark: (size) =>
      svg(
        size,
        <>
          <rect x="1" y="1" width="22" height="22" rx="6" fill="#0067A0" />
          <text x="12" y="17.5" textAnchor="middle" fontSize="15" fontWeight="700" fill="#FFFFFF" fontFamily="system-ui, sans-serif">
            S
          </text>
        </>
      )
  }
}

function fallbackMark(name: string, size: number): React.JSX.Element {
  return svg(
    size,
    <>
      <rect x="1" y="1" width="22" height="22" rx="6" fill="#4B5563" />
      <text x="12" y="17" textAnchor="middle" fontSize="14" fontWeight="700" fill="#FFFFFF" fontFamily="system-ui, sans-serif">
        {(name.trim()[0] ?? '?').toUpperCase()}
      </text>
    </>
  )
}

/** The retailer's text color, or null when it has none (use the default). */
export function retailerColor(name: string): string | null {
  return BRANDS[brandKey(name)]?.color ?? null
}

export function RetailerBadge({ name, size = 22 }: { name: string; size?: number }): React.JSX.Element {
  const brand = BRANDS[brandKey(name)]
  return brand ? brand.mark(size) : fallbackMark(name, size)
}
