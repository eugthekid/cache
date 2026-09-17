"""
api_client.py
--------------
Talks to the inventory-tracker backend -- the same POST /orders contract
bot/src/api_client.py already uses, so every claim this connector posts
goes through the exact same materialize_order/find_existing_line/
match_line pipeline a Discord checkout does.

SYNCHRONOUS on purpose, unlike bot/src/api_client.py's async client:
discord.py's bot loop is itself async and backfill can fire hundreds of
calls inside it, where a blocking call would risk missing Discord's
gateway heartbeat. This connector has no such loop to protect -- it's a
plain poll-sleep-poll cycle (see main.py) -- so a synchronous httpx.Client
is simpler and there's nothing async buys here.
"""

from typing import Optional

import httpx

import config

# One Source row for this mailbox, created the first time a claim is
# posted. Cached for the life of the process, same reasoning as bot/src/
# api_client.py's _source_cache: repopulating this via GET /sources on
# every single claim would be a lot of pointless API calls for something
# that never changes mid-run.
_source_id: Optional[str] = None


class ApiClient:
    def __init__(self, base_url: str = config.API_BASE_URL) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=15.0)

    def close(self) -> None:
        self._client.close()

    def health_check(self) -> bool:
        """Fail loudly and immediately at startup if the backend isn't
        running, rather than discovering it claim-by-claim once every
        POST starts throwing connection errors."""
        try:
            resp = self._client.get("/health")
            return resp.status_code == 200
        except httpx.RequestError:
            return False

    def get_or_create_source(self) -> str:
        """Looks up the Source row for this mailbox, creating one the
        first time it produces a claim. Matching is on
        config.email={address}, the shape models.py's own Source
        docstring already anticipates for 'email_account' -- not on
        `name`, so a source survives the user editing anything else about
        how it's displayed."""
        global _source_id
        if _source_id is not None:
            return _source_id

        resp = self._client.get("/sources")
        resp.raise_for_status()
        for source in resp.json():
            if source.get("type") == "email_account" and source.get("config", {}).get("email") == config.EMAIL_ADDRESS:
                _source_id = source["id"]
                return _source_id

        resp = self._client.post(
            "/sources",
            params={"type": "email_account", "name": f"email: {config.EMAIL_ADDRESS}"},
            json={"email": config.EMAIL_ADDRESS, "provider": "gmail"},
        )
        resp.raise_for_status()
        _source_id = resp.json()["id"]
        return _source_id

    def post_claim(self, payload: dict, source_id: str) -> Optional[dict]:
        """POSTs one claim. Returns the order as the API sees it (whether
        newly created, merged into an existing line, or the pre-existing
        match from a dedup no-op), or None when the backend answers 204 --
        which means the user previously DELETED this order, so it is
        deliberately not being re-created. Callers must treat None as
        'correctly skipped', not as an error -- same contract as bot/src/
        api_client.py's post_order."""
        resp = self._client.post("/orders", json={**payload, "source_id": source_id})
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def mark_source_synced(self) -> None:
        """Records that this mailbox is scanned up to now. Unlike
        Discord's per-channel incremental sync, this connector's actual
        high-water mark is the IMAP UID tracked in state.py -- this call
        exists only so Settings' 'last synced' display (see
        DiscordConnect.tsx's lastSyncedLabel) can show something real
        for email too, once that UI parity is built. Best-effort: a
        failure here should never abort a poll cycle that already
        successfully posted every claim."""
        if _source_id is None:
            return
        try:
            resp = self._client.patch(f"/sources/{_source_id}/synced", json={})
            resp.raise_for_status()
        except httpx.RequestError:
            pass
