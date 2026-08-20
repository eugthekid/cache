# Data Model

The schema we designed together, now implemented in `backend/app/models.py`
and applied via the Alembic migration in `backend/alembic/versions/`.

## Entities (v1 — built)

```
users
  └─< sources ─────────────┐
  └─< orders ───────────────┤ (order.source_id → sources)
        │                   │
        └─< inventory_items │
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

### `inventory_items`
One row per **physical unit** you hold — an order for `quantity=2` produces
two of these. This is the granularity resale actually needs: you might sell
one unit and keep the other, at different prices, on different dates, and
per-order aggregate tracking can't represent that.

**Business rule (enforced in `app/crud.py`, not the schema):** only orders
with `status='success'` ever produce `inventory_items` — a failed checkout
never had physical goods to track.

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
