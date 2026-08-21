"""
config.py
---------
Loads settings from a local .env file. Same pattern as discord-checkout-tracker:
secrets and machine-specific paths live in .env (git-ignored), never in code.
"""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The project root is the folder ABOVE backend/app/, so paths behave the same
# no matter which directory you run the server from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# WHY THIS PATH: a hard lesson from discord-checkout-tracker -- a SQLite
# database living inside an iCloud-synced folder (like ~/Desktop) causes
# real, hard-to-diagnose errors ("disk I/O error", "authorization denied")
# because the sync daemon can briefly lock or evict a file that's being
# actively written to. ~/Library/Application Support is never iCloud-synced,
# so the database lives there by default, safely outside the synced project
# folder -- even though the *code* itself still lives in ~/Desktop/projects/.
DEFAULT_DB_PATH = (
    Path.home() / "Library" / "Application Support" / "inventory-tracker" / "app.db"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    # SQLAlchemy connection string. Defaults to the safe local SQLite path
    # above; swapping to Postgres later is just changing this one value, e.g.
    # "postgresql+psycopg://user:pass@host/dbname".
    database_url: str = f"sqlite:///{DEFAULT_DB_PATH}"

    # Which host/port the API server binds to.
    api_host: str = "127.0.0.1"
    api_port: int = 8000


# !!! TEMPORARY -- v1-only, MUST be replaced before public launch or any
# real payment. There is no per-customer key issuance yet: every friend/
# tester activates with this same shared key. It is visible to anyone who
# inspects the app bundle, so it provides zero real security -- it exists
# only to exercise the activation screen while there are no real customers
# to issue real keys to. See the "inventory-tracker-activation-key" memory
# note for the swap-before-launch reminder.
TEST_LICENSE_KEY = "CACH-BETA-0001-TEST"


settings = Settings()

# Make sure the database's parent folder exists before SQLAlchemy tries to
# open a file there (SQLite won't create missing directories on its own).
if settings.database_url.startswith("sqlite:///"):
    db_file = settings.database_url.removeprefix("sqlite:///")
    os.makedirs(os.path.dirname(db_file), exist_ok=True)
