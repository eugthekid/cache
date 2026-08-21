# Inventory Tracker

A wide-scale inventory, spend, and (eventually) market-value tracker for
reselling — evolving from
[`discord-checkout-tracker`](../discord-checkout-tracker) into something
that can ingest from multiple sources (Discord bots, email order
confirmations, manual entry), track physical inventory unit-by-unit, and
eventually surface live market pricing. Built as a desktop app first
(Electron + React), with the data model designed so a future hosted web
product or mobile app doesn't require a rewrite.

## Status

**Backend built and verified; Discord ingestion wired up; desktop UI not
started yet.** The data model (`users` → `sources` → `orders` →
`inventory_items`, plus `app_settings`) is migrated and covered by real
HTTP tests, not just imports. Beyond basic CRUD, the API also has: dashboard
aggregation (monthly spend/revenue, aging, retailer/category breakdowns),
settings read/write, v1 license activation, and full-fidelity backup/restore
as a single `.cache` bundle. `bot/` is a separate Discord bot — ported from
`discord-checkout-tracker`, POSTing into this API instead of writing to its
own SQLite file — that backfills a channel's history and then listens live,
classifying every checkout attempt (success/failed/cancelled), not just
successes. The desktop app is still the original Electron/React shell from
the scaffold; the actual screens (designed in Claude Design, see the app's
own design canvas) haven't been built as real components yet. See
[`docs/DATA-MODEL.md`](docs/DATA-MODEL.md) for the schema and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the backend/frontend
split.

**Note on naming:** the product is now called **Cache** in the UI designs;
the project folder/repo stayed `inventory-tracker` deliberately (an internal
codename, not user-facing) — see the activation-key memory note for why.

## Project layout

| Path | What it is |
|---|---|
| `backend/` | FastAPI + SQLAlchemy + Alembic API server, SQLite for now |
| `bot/` | Discord bot — ingests checkouts into the backend via HTTP, ported from `discord-checkout-tracker` |
| `desktop/` | Electron + React + TypeScript desktop app (scaffolded with `electron-vite`, screens not yet built) |
| `docs/DATA-MODEL.md` | The entity design and the reasoning behind each decision |
| `docs/ARCHITECTURE.md` | Backend/frontend split, why, and what's verified |

## Quick start

```bash
# Backend
cd backend
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/alembic upgrade head   # creates the database
./run.sh                            # http://127.0.0.1:8000

# Discord bot (separate terminal, optional -- requires the backend running)
cd bot
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env               # fill in DISCORD_TOKEN and GUILD_ID
./run.sh

# Desktop app (separate terminal)
cd desktop
npm install
npm run dev
```

Open `http://127.0.0.1:8000/docs` for the interactive API docs (FastAPI
generates these automatically from the routers and Pydantic schemas).

## What's next

Roughly in order:

1. **Migrate existing checkout history** from `discord-checkout-tracker`'s
   database into this schema (mapping described in `docs/DATA-MODEL.md`).
   Now that the bot itself is ported, this is a one-time backfill script,
   not new ingestion logic.
2. **Build out the desktop UI** — the actual Dashboard/Orders/Inventory/
   Settings/Activation screens, designed already, wired to the real API
   instead of the current placeholder summary view.
3. **Email ingestion** — OAuth-based inbox access + structured extraction
   for order confirmations, starting with 2-3 retailers before generalizing.
4. **Market pricing (v2 schema)** — `products` + `market_prices` tables,
   starting with sneakers/streetwear (StockX-style data — note: no official
   public API, so this needs a deliberately pluggable price-source design,
   flagged in `docs/DATA-MODEL.md`).
5. **Customizable dashboard (v2, widgets)** — the dashboard mockups landed on
   individual panels having their own view switcher (e.g. the inventory-age
   panel toggling between age / retailer / category breakdowns). The natural
   next step is letting users add, remove, resize, and rearrange panels
   themselves, like a widget board, rather than shipping one fixed layout.
   That's a real feature on its own — persisted per-user layout state, a
   widget registry, grid/drag logic — not something to bolt on casually, so
   it stays explicitly out of v1 scope until the fixed dashboard has been
   used for a while and it's clear which panels people actually want to
   rearrange.
