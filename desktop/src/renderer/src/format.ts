/** Compact dollars for axis ticks and bar labels: $950, $4.2K, $12K. */
export function compactMoney(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 1000) return `$${(abs / 1000).toFixed(abs >= 10000 ? 0 : 1).replace(/\.0$/, '')}K`
  return `$${Math.round(abs)}`
}
