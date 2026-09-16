/**
 * dates.ts
 * --------
 * Helpers for the editor panels' `<input type="date">` fields, which are
 * date-only but are bound to columns that store a full timestamp
 * (orders.purchased_at, inventory_items.sold_at).
 *
 * That mismatch used to destroy data. Reading the column with
 * `.slice(0, 10)` and writing it back with `new Date(value).toISOString()`
 * round-trips a real purchase time into midnight, so an edit that only
 * added a tracking number silently threw away the hour the order was
 * actually placed -- found on 15 live orders, all stamped 00:00 on a date
 * whose ingested payload still carried the true timestamp (row
 * 2026-08-28 00:00 vs payload 2026-08-28T09:04:01.464). See
 * backend/app/backfill_overrides.py's `_is_truncation`, which deliberately
 * refuses to freeze that damage as a user override.
 *
 * Everything here works in UTC, because the tables render the date with
 * `.slice(0, 10)` on the ISO string -- i.e. the UTC date. Going through
 * local time instead would shift the displayed day for anyone west of
 * Greenwich the moment they opened an editor.
 */

/** The date an `<input type="date">` should show for a stored timestamp. */
export function toDateInput(timestamp: string | null | undefined): string {
  return timestamp ? timestamp.slice(0, 10) : ''
}

/**
 * The timestamp to PATCH when the user picks `nextDate`, keeping the
 * time-of-day the column already held.
 *
 * Changing the date is a deliberate correction of the DAY; it is not a
 * statement that the purchase happened at midnight. Carrying the original
 * clock time across means the only thing the edit changes is the thing
 * the user actually edited.
 */
export function withDatePart(original: string | null | undefined, nextDate: string): string {
  const next = new Date(`${nextDate}T00:00:00.000Z`)
  const base = original ? new Date(original) : null
  if (base && !Number.isNaN(base.getTime())) {
    next.setUTCHours(
      base.getUTCHours(),
      base.getUTCMinutes(),
      base.getUTCSeconds(),
      base.getUTCMilliseconds()
    )
  }
  return next.toISOString()
}

/**
 * The value to send for a timestamp field, or `undefined` to leave it
 * alone.
 *
 * `undefined` is dropped by JSON.stringify, so the key never reaches the
 * API, and both PATCH schemas are `exclude_unset` (see
 * backend/app/crud.py's update_order / update_inventory_item) -- an
 * omitted field keeps its stored value instead of being overwritten.
 * This is the real fix for the truncation above: an edit that doesn't
 * touch the date doesn't get to rewrite the timestamp at all.
 */
export function datePatchValue(
  original: string | null | undefined,
  nextDate: string
): string | undefined {
  if (nextDate === toDateInput(original)) return undefined
  if (!nextDate) return undefined
  return withDatePart(original, nextDate)
}
