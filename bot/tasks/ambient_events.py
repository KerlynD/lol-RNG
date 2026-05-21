"""Ambient event spawner.

Every 5 min: pick a random opted-in active user without a pending event,
post a surprise encounter in the configured channel. Aggregate per-user
cadence lands at ~20-40 min because the same user can't be re-pinged within
20 min of their last event.
"""
from __future__ import annotations

import logging
import random

import discord
from discord.ext import tasks

from bot.cogs.ambient import AMBIENT_TTL, AmbientView
from bot.db import queries
from bot.game.pve.ambient import AmbientSpec, pick_ambient

log = logging.getLogger(__name__)

CONFIG_AMBIENT_CHANNEL = "ambient_channel_id"
MAX_SPAWNS_PER_TICK = 1   # one per tick, keeps cadence sane


def _bot_ref():
    return _bot_ref.bot  # type: ignore[attr-defined]


_bot_ref.bot = None  # type: ignore[attr-defined]


def attach_bot(bot: discord.Client) -> None:
    _bot_ref.bot = bot  # type: ignore[attr-defined]


@tasks.loop(minutes=5)
async def spawn_ambient_events() -> None:
    try:
        await queries.expire_pending_ambient_events()

        channel_id_str = await queries.get_config(CONFIG_AMBIENT_CHANNEL)
        if not channel_id_str:
            return

        candidates = await queries.list_opted_in_active_users(active_days=7, ambient_cooldown_min=20)
        if not candidates:
            return

        bot = _bot_ref.bot
        if bot is None:
            return
        channel = bot.get_channel(int(channel_id_str))
        if channel is None or not isinstance(channel, discord.TextChannel):
            return

        targets = random.sample(candidates, k=min(MAX_SPAWNS_PER_TICK, len(candidates)))
        for target_id in targets:
            spec = pick_ambient()
            event = await queries.create_ambient_event(
                target_id=target_id,
                channel_id=channel.id,
                event_type=spec.key,
                ttl=AMBIENT_TTL,
            )
            view = AmbientView(event_id=event.id)
            embed = discord.Embed(
                title=f"⚔ {spec.name}",
                description=(
                    f"<@{target_id}> — {spec.flavor}\n\n"
                    f"Fight or run. You have 5 minutes to decide."
                ),
                color=0xFFC107,
            )
            try:
                msg = await channel.send(content=f"<@{target_id}>", embed=embed, view=view)
                await queries.set_ambient_message_id(event.id, msg.id)
                log.info("Spawned ambient event %s for user %s", spec.key, target_id)
            except discord.HTTPException:
                log.exception("Failed to send ambient event message")
    except Exception:
        log.exception("ambient spawner tick failed")
