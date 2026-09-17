"""
state.py
--------
Tiny local JSON file tracking the IMAP high-water mark -- see config.py's
STATE_PATH docstring for why this lives outside the API instead of on the
Source row. Deliberately minimal: one file, one dict, no migrations,
because the one thing stored here (last_uid, uidvalidity) is cheap to
lose and safe to rebuild by just re-scanning the inbox from scratch --
unlike the credential file next to it, there is nothing here that can't
be regenerated.
"""

import json
from typing import Any

from config import STATE_PATH


def load() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        # A corrupt or unreadable state file means "start over from the
        # top of the inbox" -- annoying (reprocesses mail already seen,
        # which POST /orders' own dedup on source_id+external_id makes a
        # safe no-op) but never a crash.
        return {}


def save(data: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data))
