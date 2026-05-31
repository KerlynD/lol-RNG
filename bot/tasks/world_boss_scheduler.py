"""World boss spawner — rare, random, surprise.

Every 15 min: if no active boss AND `next_spawn_at` has elapsed, spawn one
weighted-randomly from WORLD_BOSSES and reset `next_spawn_at` to NOW + 3-4 days.
Net cadence: ~1-2 bosses per week.

Also resolves expiry on the same tick.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import tasks

from bot.db import queries
from bot.game.pve.world_bosses import (
    CONFIG_BOSS_CHANNEL,
    CONFIG_NEXT_SPAWN_AT,
    WORLD_BOSSES,
    hp_scaled,
)

log = logging.getLogger(__name__)

SPAWN_INTERVAL_MIN_DAYS = 3
SPAWN_INTERVAL_MAX_DAYS = 4


def _bot_ref():
    """Late-binding shim — populated by main.py during setup_hook."""
    return _bot_ref.bot  # type: ignore[attr-defined]


_bot_ref.bot = None  # type: ignore[attr-defined]


def attach_bot(bot: discord.Client) -> None:
    _bot_ref.bot = bot  # type: ignore[attr-defined]


@tasks.loop(minutes=15)
async def sweep_and_maybe_spawn() -> None:
    try:
        # 1. Expire stale bosses
        expired = await queries.expire_old_world_bosses()
        for boss in expired:
            log.info("World boss %s (#%s) expired with %s HP remaining", boss.boss_key, boss.id, boss.hp_remaining)
            channel = _channel(boss.channel_id)
            if channel:
                spec = WORLD_BOSSES.get(boss.boss_key)
                name = spec.name if spec else boss.boss_key
                await channel.send(
                    embed=discord.Embed(
                        title=f"💀 {name} escapes!",
                        description=(
                            f"The server failed to bring down {name}. "
                            f"It fades back into legend with {boss.hp_remaining:,} HP remaining.\n\n"
                            "_No rewards distributed._"
                        ),
                        color=0x9E9E9E,
                    )
                )

        # Owner can pause all surprise spawns (e.g. overnight) via /spawns.
        if await queries.get_config("spawns_paused") == "1":
            return

        # 2. Maybe spawn
        active = await queries.get_active_world_boss()
        if active:
            return

        channel_id_str = await queries.get_config(CONFIG_BOSS_CHANNEL)
        if not channel_id_str:
            return  # No announce channel configured yet.

        next_spawn_str = await queries.get_config(CONFIG_NEXT_SPAWN_AT)
        now = datetime.now(tz=timezone.utc)
        if next_spawn_str is None:
            # First time — seed next_spawn_at and wait.
            await _schedule_next(now)
            return
        try:
            next_spawn = datetime.fromisoformat(next_spawn_str)
        except ValueError:
            await _schedule_next(now)
            return
        if now < next_spawn:
            return

        # Spawn!
        spec = _weighted_pick()
        active_users = await queries.active_users_last_7d()
        hp = hp_scaled(spec, active_users)
        channel_id = int(channel_id_str)
        boss = await queries.spawn_world_boss(spec.key, channel_id, hp, spec.window)
        await _schedule_next(now)

        channel = _channel(channel_id)
        if channel:
            await channel.send(
                content="@here",
                embed=discord.Embed(
                    title=f"🐉 {spec.name} has appeared!",
                    description=(
                        f"{spec.flavor}\n\n"
                        f"HP: **{hp:,}** · Window: **{int(spec.window.total_seconds() // 60)} min**\n"
                        f"Strike with `/strike`. Miss this and it vanishes."
                    ),
                    color=0xFFD700,
                ),
            )
        log.info("Spawned world boss %s (#%s, hp=%s)", spec.key, boss.id, hp)
    except Exception:
        log.exception("world boss scheduler tick failed")


def _channel(channel_id: int):
    bot = _bot_ref.bot
    if bot is None:
        return None
    ch = bot.get_channel(channel_id)
    if isinstance(ch, discord.TextChannel):
        return ch
    return None


def _weighted_pick():
    specs = list(WORLD_BOSSES.values())
    return random.choices(specs, weights=[s.spawn_weight for s in specs], k=1)[0]


async def _schedule_next(now: datetime) -> None:
    delta = timedelta(
        days=random.uniform(SPAWN_INTERVAL_MIN_DAYS, SPAWN_INTERVAL_MAX_DAYS)
    )
    await queries.set_config(CONFIG_NEXT_SPAWN_AT, (now + delta).isoformat())
    log.info("Next world boss scheduled for ~%s", now + delta)
