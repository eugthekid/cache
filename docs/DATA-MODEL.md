# Data Model

The schema we designed together, now implemented in `backend/app/models.py`
and applied via the Alembic migration in `backend/alembic/versions/`.

## Entities (v1 — built)

```
users
  └─< sources ─────────────┐
  └─< orders ───────────────┤ (order.source_id → sources)
  │     │                   │
  │     └─< inventory_items │
  └─< app_settings
```

### `users`
One row per person using the app. Every other table has a `user_id` from
day one — even though there's only one local user today — because
retrofitting multi-tenancy onto tables that don't already have it is far
more painful than including it from the start.

### `sources`
Where an order came from: a specific Discord channel, an email account, or
manual entry. Generalizes "which Discord channel" from
`discord-checkout-tracker` into "which ingestion connection, of any kind."
`config` is a JSON blob because every source type needs different fields
(a Discord channel needs `channel_id`/`guild_id`; an email account needs
`email`/`provider`) and new source types will keep appearing over time.

### `orders`
One row per checkout **attempt** — not just successes. `status` is
`'success' | 'failed' | 'cancelled' | 'pending'`, and `failure_reason` is
the same data the Shikari/HayhaAIO "Cancel Reason" / "Fraud Reason" fields
carried in `discord-checkout-tracker` — there it existed only to *reject* a
message from being stored; here it's stored as a first-class fact instead.

Deduplication is `UNIQUE(source_id, external_id)` — a generalization of
`discord-checkout-tracker`'s "message_id as primary key" trick to work for
any source type (an email's Message-ID header works the same way a Discord
message ID did).

`raw_product_text` and `raw_json` exist because product matching (linking an
order to a canonical catalog entry) is deliberately **deferred to v2** — see
below. Until then, the free-text product description is what's displayed
and searched on directly.

**Fulfillment fields (`orders`, migration `e12eb6e313c4`):** `shipping_status`
(`'not_shipped' | 'label_created' | 'in_transit' | 'delivered' |
'exception'`), `tracking_number`, and a ship-to address. Shipping status is
deliberately **separate from `status`**, not folded into it: an order can be
a checkout success while the package is still in transit, and a failed
checkout has no shipping state at all (rendered as `—`, not as a status).
Collapsing them into one enum would make "succeeded but not yet delivered"
unrepresentable.

The address is a short label (`Home`, `Apt 4C`, `Parents`) plus the full
address. Resellers ship to several addresses across profiles, and the label
is what a list column can usefully show. Whether this becomes its own
`addresses` table or stays denormalized on `orders` is still open — a table
is the better normalization, but it's only worth it once addresses are
reused enough to be worth managing separately.

### `inventory_items`
One row per **physical unit** you hold — an order for `quantity=2` produces
two of these. This is the granularity resale actually needs: you might sell
one unit and keep the other, at different prices, on different dates, and
per-order aggregate tracking can't represent that.

**Business rule (enforced in `app/crud.py`, not the schema):** only orders
with `status='success'` ever produce `inventory_items` — a failed checkout
never had physical goods to track. This only runs at creation time —
`PATCH /orders/{id}` editing `status` after the fact does **not**
retroactively spawn or delete `inventory_items`. Editing a typo'd status is
a rare, manual correction; silently materializing or deleting physical
units as a side effect of an edit is the kind of implicit behavior that
causes real data-integrity surprises later. If this ever needs to change,
it should be an explicit action ("create inventory for this order"), not an
implicit consequence of a status edit.

**`order_id` is nullable.** A unit usually traces back to the purchase that
created it, but not always: spreadsheet import (below) lets you record stock
you already hold with a cost basis and no purchase record behind it. Rather
than inventing a synthetic placeholder order to satisfy a NOT NULL — which
would pollute spend totals and order counts with purchases that never
happened — the link is simply absent. Anything reading `order_id` must
handle `None`; anything aggregating spend counts `orders`, and anything
counting units counts `inventory_items`, so the two stay independent.

### `app_settings`
A flexible key-value store, `(user_id, key)` unique, `value` as JSON — for
things that aren't order/inventory data: dashboard chart preferences (which
view is default, the enabled extra chart toggles), the backup schedule, and
local license state. Not split into dedicated tables per concern (no
`licenses` table, no `dashboard_preferences` table) because none of it is
relational — there's exactly one row per (user, key), and giving each its
own table would be schema surface with no query benefit. The license value
today is just the hardcoded test key described in memory — swap that logic
before public launch, not this table.

## Entities (v2 — deferred, not built yet)

```
products          id · category · name · brand · sku · image_url · external_ids (JSON)
market_prices     id · product_id (FK) · source · price_type · price · currency · fetched_at
```

- **`products`** is the canonical catalog entry a purchase resolves to (a
  specific Jordan 4 colorway, a specific card). Deliberately **not scoped to
  `user_id`** — a Jordan 4 Cool Grey is the same catalog entry for every
  user, so this table is shared, not per-account. That matters a lot if this
  ever becomes a hosted product: you don't want 50 users each with their own
  duplicate copy of the same shoe.
- **`market_prices`** is a time series, not a single "current price" column,
  so value-over-time charts are possible later.

When this phase starts, `product_id` gets added to `orders` and
`inventory_items` via a plain `ALTER TABLE` migration — no rework of
anything built in v1.

## Design decisions and why

| Decision | Why |
|---|---|
| UUID primary keys, not auto-increment integers | If this becomes a hosted product, IDs generated on different machines (e.g. an offline-first desktop client) can never collide, and merging data from multiple sources is safe. |
| Track failed/cancelled orders, not just successes | Enables analytics like "success rate per bot/profile" later, and the failure-reason data was already being captured (and thrown away) by `discord-checkout-tracker`'s detection logic. |
| Inventory tracked per physical unit | Matches how resale actually works — partial sell-through of a multi-quantity order needs distinct rows. |
| Product catalog + market pricing deferred | Get orders + inventory solid first; avoid the hardest problem (fuzzy-matching free text to a catalog) before the core workflow is even proven. |
| `products` not scoped to `user_id` | Catalog data is shared across users; order/inventory data is not. Conflating them would duplicate catalog data per user in a hosted future. |
| `inventory_items.order_id` nullable | Imported stock may have no purchase record. A synthetic placeholder order would corrupt spend totals and order counts with purchases that never happened. |
| Shipping status separate from order status | "Checkout succeeded, package still in transit" is a real and common state that one combined enum can't express. |

## Spreadsheet import

Importing an existing `.xlsx`/`.csv` is an ingestion source like any other —
it gets a `sources` row (`type='import'`, with the filename and import
timestamp in `config`), so imported orders dedup, filter, and trace back
exactly like Discord-ingested ones. Each import run being its own source row
also makes an import reversible: delete the source, delete what it created.

Two modes, because two different situations exist:

| Mode | Creates | `order_id` |
|---|---|---|
| **A purchase** — the row is a checkout, with a date/site/price | an `orders` row, plus one `inventory_items` row per quantity if `status='success'` | set |
| **A unit I hold** — the row is stock, with a cost basis and no purchase history | `quantity` standalone `inventory_items` rows directly | `NULL` |

The "unit I hold" mode is the reason `inventory_items.product_text` exists
(nullable, meaningful only when `order_id` is `NULL`): a unit linked to an
order already has a product name via `order.raw_product_text`, but a
standalone imported unit had nowhere to record what it even IS until this
field was added — found while actually building this feature, not
anticipated when the schema was first designed.

Column mapping is user-driven with auto-guessed defaults, never fixed
positions — real spreadsheets use `Item Name`/`Paid`/`Where`, not our field
names. Rows that can't be parsed (unreadable date, missing price, an
unrecognized status word) are reported and **skipped**, never silently
coerced to a default, and the row count shown on the confirm button is the
count that will actually be written — `preview` and `commit` run every row
through the exact same evaluation function specifically so those two can
never disagree.

Duplicates match on **`order_number` alone**, checked against every
existing order regardless of source — not `(source, external_id)` the way
Discord ingestion dedups. That's deliberate, not an oversight: each import
run gets its own fresh `sources` row (see below), so `source_id` is never
shared across two imports, or between an import and a Discord-ingested
order for the same real-world purchase — only the order number itself can
catch a duplicate across sources. Rows sharing an order number *within the
same file* are also caught, not just ones already in the database.
Duplicates are **skipped rather than merged**, consistent with Discord
dedup: re-importing a corrected spreadsheet won't update existing rows; an
"update existing" mode is a separate, later decision.

## Migrating existing `discord-checkout-tracker` data

Nothing from that project is lost when this is ready — the mapping is
mechanical:

- each distinct Discord channel → one `sources` row (`type='discord_channel'`)
- each existing `checkouts` row → one `orders` row (`status='success'`,
  since the old bot only ever stored successes)
- each unit of `quantity` → one `inventory_items` row, defaulted to
  `status='in_hand'` (update later as things actually sell)

This migration script doesn't exist yet — write it when email ingestion (or
another second source) makes having more than one order in the system
worth actually testing against.
