"""
main.py
-------
The FastAPI application. Run it with:
    uvicorn app.main:app --reload --port 8000
(or just `./run.sh` from the backend/ folder)
"""

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.routers import backup, bot_service, dashboard, discord, inventory, license, orders, products, sources, sync
from app.routers import import_ as import_router
from app.routers import settings as settings_router

app = FastAPI(title="Inventory Tracker API")

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
app.include_router(sync.router)
app.include_router(bot_service.router)
app.include_router(products.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/me")
def me(db: Session = Depends(get_db)):
    """Lets a client discover the local user's id without hardcoding it."""
    user = crud.get_or_create_default_user(db)
    return {"id": user.id, "email": user.email}
