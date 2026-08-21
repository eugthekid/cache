/**
 * The ambient wavy-line background from the design canvas -- one shared
 * component instead of copy-pasted SVG in every screen, so a future tweak
 * (color, path shape) happens in one place.
 */
function WavyBackground(): React.JSX.Element {
  return (
    <svg
      width="1440"
      height="900"
      viewBox="0 0 1440 900"
      style={{
        position: 'absolute',
        inset: 0,
        filter: 'blur(1.5px)',
        pointerEvents: 'none',
        width: '100%',
        height: '100%'
      }}
    >
      <defs>
        <linearGradient id="wv1" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="oklch(70% 0.15 250)" stopOpacity="0" />
          <stop offset="35%" stopColor="oklch(70% 0.15 250)" stopOpacity="0.55" />
          <stop offset="70%" stopColor="oklch(68% 0.18 320)" stopOpacity="0.5" />
          <stop offset="100%" stopColor="oklch(68% 0.18 340)" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="wv2" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="oklch(75% 0.1 230)" stopOpacity="0" />
          <stop offset="45%" stopColor="oklch(75% 0.12 230)" stopOpacity="0.32" />
          <stop offset="100%" stopColor="oklch(70% 0.16 330)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path
        d="M -100 60 C 250 -40, 420 180, 700 140 S 1150 40, 1560 340"
        stroke="url(#wv1)"
        strokeWidth="2.5"
        fill="none"
      />
      <path
        d="M -100 120 C 280 20, 440 240, 720 200 S 1180 100, 1560 400"
        stroke="url(#wv1)"
        strokeWidth="1.5"
        fill="none"
        opacity="0.7"
      />
      <path
        d="M -100 20 C 220 -80, 380 120, 660 90 S 1120 -20, 1560 260"
        stroke="url(#wv2)"
        strokeWidth="1"
        fill="none"
      />
      <path
        d="M -100 780 C 260 900, 480 640, 780 700 S 1200 920, 1560 640"
        stroke="url(#wv2)"
        strokeWidth="1.8"
        fill="none"
        opacity="0.55"
      />
    </svg>
  )
}

export default WavyBackground
