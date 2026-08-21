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

**Desktop app — verified running.** `npm run dev` launches the actual
Electron process (confirmed alive via its PID, not just "the command didn't
error"), connected to the backend.

### Known issue: `extract-zip` silently breaks Electron's install

The first `npm install` produced an `electron` package with **no actual
binary** — `node_modules/electron/dist/` contained only a license file.
`npm audit` explains why: `extract-zip` (which Electron's own postinstall
script uses to unpack itself) has a symlink-safety patch that silently
truncates extraction of any zip containing symlinks — and every macOS
`.app` bundle is full of them. The download itself is fine (verified: 585
files, valid checksum); the extraction just quietly stops after the first
non-symlink entry, with no error anywhere.

**Fix applied:** the cached zip
(`~/Library/Caches/electron/<hash>/electron-v<version>-darwin-arm64.zip`)
was extracted manually with the system's `unzip` instead:

```bash
cd desktop
rm -rf node_modules/electron/dist
mkdir -p node_modules/electron/dist
unzip -q ~/Library/Caches/electron/*/electron-v*-darwin-arm64.zip -d node_modules/electron/dist
printf 'Electron.app/Contents/MacOS/Electron' > node_modules/electron/path.txt   # printf, not echo -- no trailing newline
```

That last line matters: `echo` appends a trailing `\n`, and Electron's
launcher doesn't trim it, which produces a corrupted path and an `ENOENT`
that's easy to misread as "the binary is missing" when it's actually just
a malformed path string.

**If a future `npm install` breaks this again** (e.g. after `rm -rf
node_modules`), re-run the fix above rather than assuming Electron itself
is broken. The `npm audit fix --force` suggestion (bumping Electron to a
new major version) was deliberately not applied — a breaking version bump
isn't the right fix for what's actually a bug in a transitive dependency's
overly-aggressive security patch.

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
