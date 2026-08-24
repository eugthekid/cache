"""
api_client.py
-------------
Replaces discord-checkout-tracker's database.py: instead of writing
directly to a local SQLite file, every parsed checkout is POSTed to the
inventory-tracker backend's HTTP API.

Async on purpose (httpx.AsyncClient, not `requests`): discord.py's bot loop
is itself async, and backfill_history() can make hundreds of sequential API
calls walking a channel's history. A blocking synchronous HTTP call there
would stall the bot's event loop long enough to miss Discord's gateway
heartbeat and get disconnected -- this only matters for backfill's *volume*
of calls, not for any single call being slow.

Dedup is NOT handled here: POST /orders is already idempotent on
(source_id, external_id) server-side (see backend/app/routers/orders.py),
so re-running a backfill safely no-ops on checkouts already stored, the
same "safe to re-run" property discord-checkout-tracker's own upsert had.
"""

from typing import Optional

import httpx

from config import API_BASE_URL

# One Source row per Discord channel, created (or looked up) the first time
# a checkout is seen there. Cached in memory for the life of the process --
# repopulating this via GET /sources on every single message would be a lot
# of pointless API calls for something that never changes mid-run.
_source_cache: dict[int, str] = {}


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=15.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_or_create_source(self, channel_id: int, channel_name: str, guild_id: int) -> str:
        """Looks up the Source row for this Discord channel, creating one
        the first time this channel produces a checkout. Matching is on
        config.channel_id, not name -- a channel can be renamed in Discord
        without that creating a second, orphaned Source."""
        if channel_id in _source_cache:
            return _source_cache[channel_id]

        resp = await self._client.get("/sources")
        resp.raise_for_status()
        for source in resp.json():
            if source.get("config", {}).get("channel_id") == str(channel_id):
                _source_cache[channel_id] = source["id"]
                return source["id"]

        resp = await self._client.post(
            "/sources",
            params={"type": "discord_channel", "name": f"#{channel_name}"},
            json={"channel_id": str(channel_id), "guild_id": str(guild_id)},
        )
        resp.raise_for_status()
        source_id = resp.json()["id"]
        _source_cache[channel_id] = source_id
        return source_id

    async def post_order(self, record: dict, source_id: str) -> dict:
        """POSTs one parsed checkout. Returns the order as the API sees it
        (whether newly created or the pre-existing match from a dedup
        no-op) -- callers use this to tell "new" from "already had it"."""
        resp = await self._client.post("/orders", json={**record, "source_id": source_id})
        resp.raise_for_status()
        return resp.json()

    async def get_source_last_synced(self, source_id: str) -> Optional[str]:
        """The high-water mark for a channel: the bot only reads messages
        newer than this on a normal startup (see mark_source_synced)."""
        resp = await self._client.get("/sources")
        resp.raise_for_status()
        for source in resp.json():
            if source["id"] == source_id:
                return source.get("last_synced_at")
        return None

    async def mark_source_synced(self, source_id: str) -> None:
        """Records that this channel is scanned up to now, so the next
        startup can skip everything already seen instead of re-walking the
        whole history."""
        resp = await self._client.patch(f"/sources/{source_id}/synced", json={})
        resp.raise_for_status()

    async def claim_sync_request(self) -> tuple[bool, bool]:
        """Polls for a Resync requested from the desktop app. Returns
        (claimed, full). Claiming clears the flag server-side, so one click
        produces exactly one scan."""
        try:
            resp = await self._client.post("/sync/claim")
            resp.raise_for_status()
            data = resp.json()
            return bool(data.get("claimed")), bool(data.get("full"))
        except httpx.RequestError:
            # Backend momentarily unreachable is not fatal for a poll -- the
            # request stays pending and the next tick will pick it up.
            return False, False

    async def health_check(self) -> bool:
        """Used at startup to fail loudly and immediately if the backend
        isn't running, rather than discovering it message-by-message once
        every POST starts throwing connection errors."""
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except httpx.RequestError:
            return False
