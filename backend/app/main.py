"""
main.py
-------
The FastAPI application. Run it with:
    uvicorn app.main:app --reload --port 8000
(or just `./run.sh` from the backend/ folder)
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import crud, email_poller, tracking_poller
from app.database import get_db
from app.routers import backup, bot_service, catalog, dashboard, discord, email_account, inventory, license, orders, products, sources, sync, tracking_account
from app.routers import import_ as import_router
from app.routers import settings as settings_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Starts the email poller if a connection is already saved from a
    # previous run -- nothing happens if it isn't configured yet (see
    # email_poller.start()). No LaunchAgent, no second process: the
    # poller is a daemon thread inside THIS process, which is why it
    # only needs starting/stopping here and after every successful
    # /email/configure (see routers/email_account.py) rather than
    # anything install/uninstall-shaped. tracking_poller.py is the same
    # shape, for the live-tracking provider (see routers/tracking_account.py).
    email_poller.start()
    tracking_poller.start()
    yield
    email_poller.stop()
    tracking_poller.stop()


app = FastAPI(title="Inventory Tracker API", lifespan=lifespan)

# The desktop app (Electron/React) runs on a different origin (a local dev
# server port, or the file:// origin once packaged) than this API, so the
# browser's CORS policy would otherwise block requests between them.
# Wide open ("*") is fine for now -- this only ever listens on localhost,
# there's no real multi-origin exposure yet.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sources.router)
app.include_router(orders.router)
app.include_router(inventory.router)
app.include_router(dashboard.router)
app.include_router(settings_router.router)
app.include_router(license.router)
app.include_router(backup.router)
app.include_router(import_router.router)
app.include_router(discord.router)
app.include_router(email_account.router)
app.include_router(sync.router)
app.include_router(bot_service.router)
app.include_router(catalog.router)
app.include_router(products.router)
app.include_router(tracking_account.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/me")
def me(db: Session = Depends(get_db)):
    """Lets a client discover the local user's id without hardcoding it."""
    user = crud.get_or_create_default_user(db)
    return {"id": user.id, "email": user.email}
