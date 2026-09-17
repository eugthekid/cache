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
import os
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
    """Writes via a temp file + atomic rename, not a direct write_text().
    A plain write_text() opens, writes, then closes -- a process killed
    or a machine that sleeps mid-write (this runs unattended, on a timer,
    exactly the kind of process that gets interrupted by a laptop lid
    closing) can leave a half-written, truncated JSON file behind.
    load()'s own JSONDecodeError handling already degrades that
    gracefully (just rescans from the top), but avoiding it costs
    nothing: os.replace() is atomic on both APFS and HFS+, so a reader
    always sees either the complete old file or the complete new one,
    never something in between."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = STATE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data))
    os.replace(tmp_path, STATE_PATH)
