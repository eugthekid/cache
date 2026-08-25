"""
bot.py
------
The Discord bot. Three jobs now:

  1. BACKFILL -- on startup, scans each watched channel and POSTs every
                 checkout-shaped embed to the backend. INCREMENTAL by
                 default (only messages newer than that channel's
                 last_synced_at), which keeps startup fast once a server
                 has real history behind it; the first run has no
                 high-water mark and so is naturally a full walk.
  2. LIVE     -- stays connected and POSTs each new one as it's posted.
  3. RESYNC   -- polls the backend for a Resync requested from the Cache
                 desktop app, and re-scans on demand (full or incremental).
                 Polling, not a callback: this process has no inbound
                 address, so the bot has to ask. See backend routers/sync.py.

Dropped from discord-checkout-tracker: the /export and /stats slash
commands. inventory-tracker has its own Orders and Dashboard screens
covering that need directly against the database -- no reason to duplicate
filtering/export logic here too.

Run it with: python src/bot.py
Requires the backend running first (../backend/run.sh) -- checked at
startup so this fails loudly and immediately rather than discovering it
message-by-message once every POST starts throwing connection errors.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord

import config
import parser as checkout_parser
from api_client import ApiClient

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True


class CheckoutBot(discord.Client):
    # How often to check whether the desktop app asked for a resync.
    RESYNC_POLL_SECONDS = 20

    def __init__(self, api: ApiClient) -> None:
        super().__init__(intents=intents)
        self.api = api
        self._backfilled = False

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user}.")
        if self._backfilled:
            return
        self._backfilled = True
        # Incremental on startup: only messages newer than each channel's
        # last_synced_at. A first run (nothing synced yet) is naturally a
        # full walk, because there's no high-water mark to start from.
        await self.backfill_history(full=False)
        self.loop.create_task(self._watch_for_resync())

    async def _watch_for_resync(self) -> None:
        """Polls the backend for a Resync requested from the desktop app.
        Polling rather than the app calling us: the bot is a separate
        process with no inbound address, so this is the only direction that
        works without asking the user to open a port."""
        while not self.is_closed():
            await asyncio.sleep(self.RESYNC_POLL_SECONDS)
            # The scan is inside the try as well as the poll: an exception
            # from backfill_history would otherwise kill this task outright,
            # silently disabling every future resync until the bot is
            # restarted, while the process kept running and looking healthy.
            try:
                claimed, full = await self.api.claim_sync_request()
                if claimed:
                    kind = "full" if full else "incremental"
                    print(f"Resync requested from Cache ({kind}). Scanning...")
                    await self.backfill_history(full=full)
            except Exception as exc:  # never let one bad scan end the loop
                print(f"(resync failed: {exc!r} -- will retry on the next poll)")

    def _channels_to_scan(self, guild: discord.Guild) -> list[discord.abc.Messageable]:
        if config.SCAN_ALL_CHANNELS:
            return [ch for ch in guild.text_channels if ch.id != config.CHANGELOG_CHANNEL_ID]
        channels = []
        for cid in config.CHANNEL_IDS:
            if cid == config.CHANGELOG_CHANNEL_ID:
                continue
            ch = self.get_channel(cid)
            if ch is not None:
                channels.append(ch)
        return channels

    async def backfill_history(self, full: bool = True) -> None:
        guild = self.get_guild(config.GUILD_ID)
        if guild is None:
            print(f"Could not find server {config.GUILD_ID}. Is the bot in it?")
            return

        channels = self._channels_to_scan(guild)
        scope = "all channels" if config.SCAN_ALL_CHANNELS else f"{len(channels)} channel(s)"
        mode = "full history" if full else "new messages only"
        print(f"Scanning {scope} in {guild.name} ({mode})...")

        total_sent = 0
        total_skipped = 0
        total_dismissed = 0
        for channel in channels:
            source_id = await self.api.get_or_create_source(channel.id, channel.name, guild.id)

            after = None
            if not full:
                last_synced = await self.api.get_source_last_synced(source_id)
                if last_synced:
                    # discord.py wants a datetime for `after`; an aware one,
                    # since Discord timestamps are UTC.
                    parsed = datetime.fromisoformat(last_synced)
                    after = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            try:
                # oldest_first=True, limit=None: walk the whole channel from
                # the start, same as discord-checkout-tracker. Dedup is the
                # API's job now (POST /orders is idempotent on
                # source_id+external_id), so re-running this is always safe.
                async for message in channel.history(limit=None, oldest_first=True, after=after):
                    record = checkout_parser.parse_message(message)
                    if not record:
                        continue
                    if not config.matches_profile_filter(record.get("profile")):
                        total_skipped += 1
                        continue
                    order = await self.api.post_order(record, source_id)
                    if order is None:
                        # Previously deleted in Cache -- deliberately not
                        # re-created. Counted so the summary doesn't look
                        # like the scan silently lost messages.
                        total_dismissed += 1
                    else:
                        total_sent += 1
            except discord.Forbidden:
                print(f"  (no access to #{channel.name}, skipping)")
            except discord.HTTPException as exc:
                print(f"  (error reading #{channel.name}: {exc}, skipping)")
            else:
                # Only advance the high-water mark when the channel was read
                # without error -- otherwise a transient failure would make
                # the next incremental run skip the messages we just missed.
                await self.api.mark_source_synced(source_id)

        notes = []
        if total_skipped:
            notes.append(f"{total_skipped} skipped -- didn't match PROFILE_FILTER")
        if total_dismissed:
            notes.append(f"{total_dismissed} left out -- deleted in Cache")
        suffix = f" ({'; '.join(notes)})" if notes else ""
        print(f"Backfill complete: {total_sent} checkouts sent to the backend{suffix}.")
        print("Now listening for new checkouts.")

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.guild.id != config.GUILD_ID:
            return
        if not config.should_scan(message.channel.id):
            return
        record = checkout_parser.parse_message(message)
        if not record:
            return
        if not config.matches_profile_filter(record.get("profile")):
            return

        source_id = await self.api.get_or_create_source(
            message.channel.id, message.channel.name, message.guild.id
        )
        order = await self.api.post_order(record, source_id)
        if order is None:
            # A checkout the user already deleted, posted again live.
            return
        print(
            f"Logged {order['status']} checkout in #{message.channel.name}: "
            f"{record.get('raw_product_text')} (profile: {record.get('profile') or '?'})"
        )


async def main() -> None:
    api = ApiClient()
    if not await api.health_check():
        raise RuntimeError(
            f"Can't reach the backend at {config.API_BASE_URL}. "
            f"Start it first: cd ../backend && ./run.sh"
        )

    bot = CheckoutBot(api)
    try:
        await bot.start(config.DISCORD_TOKEN)
    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
