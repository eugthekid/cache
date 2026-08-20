# Architecture

## The split: Python backend, Electron/React frontend

```
┌─────────────────────┐        HTTP (localhost:8000)        ┌──────────────────────┐
│  backend/            │◄────────────────────────────────────┤  desktop/              │
│  FastAPI + SQLAlchemy │                                     │  Electron + React + TS │
│  → SQLite (local)     │                                     │  (renderer talks to    │
│                       │                                     │   the API via fetch)   │
└─────────────────────┘                                       └──────────────────────┘
```

**Why Python for the backend:** `discord-checkout-tracker` already has a
real, battle-tested ingestion layer — Discord embed parsing, the multi-bot
success/failure detection heuristics, database logic. None of that gets
thrown away; it becomes the foundation this project's ingestion sources
(Discord, later email) are built on.

**Why Electron + React for the frontend, not a Python GUI:** the deciding
factor was "could become a product later." React components built for this
desktop app are *the same components* that would become a hosted web
version if this turns into a multi-user product, and the same patterns
carry over to React Native if mobile becomes real. A Python-only desktop UI
wouldn't give that reuse.

**Why they're separate processes talking over HTTP, not one process:** this
is the same pattern real products use (a local backend service + a UI that
talks to it), and it means the backend is independently testable — every
business rule in this scaffold was verified with real HTTP requests before
any UI code existed, without needing a rendered window at all.

## What's verified vs. what isn't (as of this scaffold)

**Backend — fully verified**, via real HTTP requests against a running
server (not just "it compiles"):
- Schema migration applies cleanly and matches `models.py` exactly
- Creating a `success` order with `quantity=2` spawns exactly 2
  `inventory_items`
- Creating a `failed` order spawns zero `inventory_items` (the business
  rule holds)
- Re-posting the same `(source_id, external_id)` returns the existing
  order rather than duplicating it (dedup works)
- `/inventory/summary` aggregates correctly

**Desktop app — partially verified.** The production build compiles
cleanly (`npm run build`, zero errors — this runs the actual TypeScript
compiler and bundler over the real `App.tsx`/`api.ts` code, not a stub).
TypeScript typechecks cleanly. The Vite dev server confirmed it starts and
serves. What's **not** verified from this environment: the live-rendered
result in an actual Electron window, since that needs a real display this
sandboxed environment doesn't have. Run `npm run dev` from `desktop/` on
your own machine to see it — that's also the correct way to check a desktop
GUI app in general, not a limitation specific to this project.

## Local development

```bash
# Terminal 1 — backend
cd backend
python3 -m venv .venv        # first time only
./.venv/bin/pip install -r requirements.txt   # first time only
./.venv/bin/alembic upgrade head              # first time only (creates the DB)
./run.sh

# Terminal 2 — desktop app
cd desktop
npm install                  # first time only
npm run dev
```

The backend must be running before the desktop app can load data — the app
shows a clear "couldn't reach the backend" message if it isn't.

## Where the database lives

`~/Library/Application Support/inventory-tracker/app.db` — **not** inside
this project folder, even though the folder itself lives under
`~/Desktop/projects/`. That's a deliberate lesson carried over from
`discord-checkout-tracker`: a SQLite database inside an iCloud-synced folder
(like `~/Desktop`) causes real, hard-to-diagnose errors, because the sync
daemon can briefly lock or evict a file that's being actively written to.
See `backend/app/config.py` for the exact reasoning.
