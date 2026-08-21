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

**Scaffold stage.** The backend's core data model (`users` → `sources` →
`orders` → `inventory_items`) is built, migrated, and verified against real
HTTP requests. The desktop app is a working Electron/React/TypeScript shell
that connects to the backend and displays a live inventory summary. Nothing
ingests real data yet — no Discord bot, no email scraping, no market
pricing. See [`docs/DATA-MODEL.md`](docs/DATA-MODEL.md) for the schema and
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the backend/frontend
split and what's been verified so far.

## Project layout

| Path | What it is |
|---|---|
| `backend/` | FastAPI + SQLAlchemy + Alembic API server, SQLite for now |
| `desktop/` | Electron + React + TypeScript desktop app (scaffolded with `electron-vite`) |
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

# Desktop app (separate terminal)
cd desktop
npm install
npm run dev
```

Open `http://127.0.0.1:8000/docs` for the interactive API docs (FastAPI
generates these automatically from the routers and Pydantic schemas).

## What's next

Roughly in order:

1. **Port Discord ingestion** — adapt `discord-checkout-tracker`'s bot to
   POST into this API's `/orders` endpoint instead of writing to its own
   SQLite table directly. The parsing/detection logic (multi-bot
   success/failure classification) carries over almost unchanged; see
   `docs/DATA-MODEL.md` for how `status`/`failure_reason` map onto it.
2. **Migrate existing checkout history** from `discord-checkout-tracker`'s
   database into this schema (mapping described in `docs/DATA-MODEL.md`).
3. **Build out the desktop UI** — an actual orders/inventory list, not just
   a summary screen.
4. **Email ingestion** — OAuth-based inbox access + structured extraction
   for order confirmations, starting with 2-3 retailers before generalizing.
5. **Market pricing (v2 schema)** — `products` + `market_prices` tables,
   starting with sneakers/streetwear (StockX-style data — note: no official
   public API, so this needs a deliberately pluggable price-source design,
   flagged in `docs/DATA-MODEL.md`).
6. **Customizable dashboard (v2, widgets)** — the dashboard mockups landed on
   individual panels having their own view switcher (e.g. the inventory-age
   panel toggling between age / retailer / category breakdowns). The natural
   next step is letting users add, remove, resize, and rearrange panels
   themselves, like a widget board, rather than shipping one fixed layout.
   That's a real feature on its own — persisted per-user layout state, a
   widget registry, grid/drag logic — not something to bolt on casually, so
   it stays explicitly out of v1 scope until the fixed dashboard has been
   used for a while and it's clear which panels people actually want to
   rearrange.
