from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from bot.config import Settings
from bot.db import migrate, pool
from bot.tasks import ambient_events as ambient_events_task
from bot.tasks import world_boss_scheduler as world_boss_task
from bot.tasks.reap_expiry import sweep_expired_reap_marks
from bot.tasks.trade_expiry import sweep_expired_trades
from bot.utils.gating import AdventureGatedTree

log = logging.getLogger("lol-rng")

COGS = (
    "bot.cogs.admin",
    "bot.cogs.adventure",
    "bot.cogs.menu",
    "bot.cogs.rolling",
    "bot.cogs.inventory",
    "bot.cogs.loadout",
    "bot.cogs.actions",
    "bot.cogs.pve",
    "bot.cogs.pvp",
    "bot.cogs.ambient",
    "bot.cogs.settings",
    "bot.cogs.worldboss",
    "bot.cogs.trading",
    "bot.cogs.godlike",
    "bot.cogs.prestige",
)


class LolRngBot(commands.Bot):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = False
        # Custom tree gates every game command behind /start-adventure.
        super().__init__(
            command_prefix="!", intents=intents, tree_cls=AdventureGatedTree
        )
        self.settings = settings

    async def setup_hook(self) -> None:
        await pool.init_pool(self.settings.database_url)
        await migrate.run(self.settings.drop_weight_seed)

        for cog in COGS:
            try:
                await self.load_extension(cog)
            except Exception:
                log.exception("Failed to load %s", cog)
                raise

        guild = discord.Object(id=self.settings.discord_guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("Synced %d slash commands to guild %s", len(synced), self.settings.discord_guild_id)

        sweep_expired_trades.start()
        sweep_expired_reap_marks.start()
        world_boss_task.attach_bot(self)
        ambient_events_task.attach_bot(self)
        world_boss_task.sweep_and_maybe_spawn.start()
        ambient_events_task.spawn_ambient_events.start()
        log.info("Background sweeps + schedulers started.")

    async def close(self) -> None:
        try:
            for loop_task in (
                sweep_expired_trades,
                sweep_expired_reap_marks,
                world_boss_task.sweep_and_maybe_spawn,
                ambient_events_task.spawn_ambient_events,
            ):
                if loop_task.is_running():
                    loop_task.cancel()
            await pool.close_pool()
        finally:
            await super().close()


async def amain() -> None:
    settings = Settings.load()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bot = LolRngBot(settings)
    async with bot:
        await bot.start(settings.discord_token)


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
