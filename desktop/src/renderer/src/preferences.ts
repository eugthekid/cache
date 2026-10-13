/** Small per-device display preferences, kept in localStorage. */

export type VariantsLayout = 'table' | 'cards' | 'split'

export const VARIANTS_LAYOUTS: { key: VariantsLayout; label: string; sub: string }[] = [
  { key: 'table', label: 'Table', sub: 'Compact rows with a picture and the counts for each variant' },
  { key: 'cards', label: 'Cards', sub: 'A card per variant with a larger picture' },
  { key: 'split', label: 'List + detail', sub: 'Pick a variant on the left, see its numbers on the right' }
]

const KEY = 'cache_variants_layout'

export function getVariantsLayout(): VariantsLayout {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'cards' || v === 'split' || v === 'table') return v
  } catch {
    // storage blocked: fall through to the default
  }
  return 'table'
}

export function setVariantsLayout(layout: VariantsLayout): void {
  try {
    localStorage.setItem(KEY, layout)
  } catch {
    // a blocked localStorage just means the choice isn't remembered
  }
}
