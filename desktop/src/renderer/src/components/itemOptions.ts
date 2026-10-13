/** Pick lists for the item-details dropdowns. */

export const PRODUCT_TYPES = [
  'Elite Trainer Box',
  'Booster Box',
  'Booster Bundle',
  'Booster Pack',
  'Tin',
  'Mini Tin Set',
  'Blister',
  'Collection Box',
  'Premium Collection',
  'Figure Collection',
  'Sticker Collection',
  'Poster Collection',
  'Plush',
  'Apparel',
  'Other'
]

const DEFAULT_CATEGORIES = ['Pokémon TCG', 'One Piece', 'Sneakers / Clothing']

/** The defaults plus whatever categories already exist in the data, so a
 * category you've used before is always offered. */
export function categoryOptions(existing: string[]): string[] {
  return Array.from(new Set([...DEFAULT_CATEGORIES, ...existing])).sort((a, b) => a.localeCompare(b))
}

/** `options` with the current value included, so a value that isn't on the
 * list (an old free-text category) still shows instead of looking blank. */
export function withCurrent(options: string[], current: string | null): string[] {
  return current && !options.includes(current) ? [...options, current] : options
}
