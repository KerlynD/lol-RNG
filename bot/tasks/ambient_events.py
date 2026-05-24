"""Ambient event spawner.

Every 10 min: with 50% chance, pick one random opted-in active user without
a pending event and post a surprise encounter. Combined with the per-user
60-min cooldown floor below, aggregate per-user cadence lands at roughly
1-2 hours between pings — random encounters should feel rare and tasteful,
not constant.
"""
from __future__ import annotations

import logging
import random

import discord
from discord.ext import tasks

from bot.cogs.ambient import AMBIENT_TTL, AmbientView
from bot.db import queries
from bot.game.combat import power_score
from bot.game.pve.ambient import AmbientSpec, pick_ambient
from bot.game.pve.combat import (
    PVE_WIN_PCT_BY_DIFF,
    WEAKNESS_BONUS_PCT,
)

log = logging.getLogger(__name__)

CONFIG_AMBIENT_CHANNEL = "ambient_channel_id"
MAX_SPAWNS_PER_TICK = 1            # one per tick, keeps cadence sane
PER_USER_COOLDOWN_MIN = 60         # SQL filter: don't re-ping within 1 hour
SPAWN_CHANCE_PER_TICK = 0.5        # adds variance so ticks don't feel clockwork


def _bot_ref():
    return _bot_ref.bot  # type: ignore[attr-defined]


_bot_ref.bot = None  # type: ignore[attr-defined]


def attach_bot(bot: discord.Client) -> None:
    _bot_ref.bot = bot  # type: ignore[attr-defined]


@tasks.loop(minutes=10)
async def spawn_ambient_events() -> None:
    try:
        await queries.expire_pending_ambient_events()

        channel_id_str = await queries.get_config(CONFIG_AMBIENT_CHANNEL)
        if not channel_id_str:
            return

        # Coin-flip per tick — keeps the rhythm from feeling mechanical.
        if random.random() >= SPAWN_CHANCE_PER_TICK:
            return

        candidates = await queries.list_opted_in_active_users(
            active_days=7, ambient_cooldown_min=PER_USER_COOLDOWN_MIN
        )
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

            # Compute a win-% preview based on the target's best alive champion.
            preview_lines = [
                f"<@{target_id}> — {spec.flavor}",
                "",
                f"**{spec.name}** — Tier {spec.tier}"
                + (f" · weak to {spec.weak_to}" if spec.weak_to else ""),
            ]
            try:
                loadout = await queries.alive_loadout(target_id)
                if loadout:
                    lead = max((e.champion for e in loadout), key=power_score)
                    diff = max(-4, min(4, lead.tier - spec.tier))
                    win_pct = PVE_WIN_PCT_BY_DIFF[diff]
                    if spec.weak_to and lead.damage_type == spec.weak_to:
                        win_pct = min(99.0, win_pct + WEAKNESS_BONUS_PCT)
                    preview_lines.append(
                        f"Your best alive champion: **{lead.name}** (T{lead.tier}, {lead.damage_type})"
                    )
                    preview_lines.append(f"Estimated win chance: **{win_pct:.1f}%**")
                else:
                    preview_lines.append("_You have no alive champion — running is your only option._")
            except Exception:
                log.exception("Failed to compute ambient win preview")
            preview_lines.append("")
            preview_lines.append("Fight or run. You have 5 minutes to decide.")

            embed = discord.Embed(
                title=f"⚔ {spec.name}",
                description="\n".join(preview_lines),
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
