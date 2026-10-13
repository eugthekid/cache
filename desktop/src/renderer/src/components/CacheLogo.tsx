import logo from '../assets/cache-logo.png'

/** The Cache app icon, so the logo in the app matches the one on the dock. */
function CacheLogo({ size = 28, glow = true }: { size?: number; glow?: boolean }): React.JSX.Element {
  return (
    <img
      src={logo}
      alt="Cache"
      width={size}
      height={size}
      style={{
        flex: 'none',
        borderRadius: size * 0.225,
        boxShadow: glow ? `0 0 ${Math.round(size * 0.7)}px -2px oklch(70% 0.15 240 / 0.55)` : undefined
      }}
    />
  )
}

export default CacheLogo
