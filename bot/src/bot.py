"""
bot.py
------
The Discord bot. Two jobs, same as discord-checkout-tracker's:

  1. BACKFILL -- on startup, walks each watched channel's full history and
                 POSTs every checkout-shaped embed found to the backend.
  2. LIVE     -- stays connected and POSTs each new one as it's posted.

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord

import config
import parser as checkout_parser
from api_client import ApiClient

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True


class CheckoutBot(discord.Client):
    def __init__(self, api: ApiClient) -> None:
        super().__init__(intents=intents)
        self.api = api
        self._backfilled = False

    async def on_ready(self) -> None:
        print(f"Logged in as {self.user}. Reading channel history...")
        if self._backfilled:
            return
        self._backfilled = True
        await self.backfill_history()

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

    async def backfill_history(self) -> None:
        guild = self.get_guild(config.GUILD_ID)
        if guild is None:
            print(f"Could not find server {config.GUILD_ID}. Is the bot in it?")
            return

        channels = self._channels_to_scan(guild)
        scope = "all channels" if config.SCAN_ALL_CHANNELS else f"{len(channels)} channel(s)"
        print(f"Scanning {scope} in {guild.name}...")

        total_sent = 0
        for channel in channels:
            source_id = await self.api.get_or_create_source(channel.id, channel.name, guild.id)
            try:
                # oldest_first=True, limit=None: walk the whole channel from
                # the start, same as discord-checkout-tracker. Dedup is the
                # API's job now (POST /orders is idempotent on
                # source_id+external_id), so re-running this is always safe.
                async for message in channel.history(limit=None, oldest_first=True):
                    record = checkout_parser.parse_message(message)
                    if record:
                        await self.api.post_order(record, source_id)
                        total_sent += 1
            except discord.Forbidden:
                print(f"  (no access to #{channel.name}, skipping)")
            except discord.HTTPException as exc:
                print(f"  (error reading #{channel.name}: {exc}, skipping)")

        print(f"Backfill complete: {total_sent} checkouts sent to the backend.")
        print("Now listening for new checkouts.")

    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None or message.guild.id != config.GUILD_ID:
            return
        if not config.should_scan(message.channel.id):
            return
        record = checkout_parser.parse_message(message)
        if not record:
            return

        source_id = await self.api.get_or_create_source(
            message.channel.id, message.channel.name, message.guild.id
        )
        order = await self.api.post_order(record, source_id)
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
