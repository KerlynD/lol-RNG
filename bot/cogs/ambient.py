"""Ambient encounter cog — registers a persistent View for surprise encounters.

The View's buttons survive restarts via deterministic custom_id encoding
the ambient_event id.
"""
from __future__ import annotations

import logging
import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.champions.abilities import progress_win_bonus
from bot.game.champions.leveling import AMBIENT_WIN_XP, EXPLORE_PASSIVE_SHARE
from bot.game.champions.xp import award_champ_xp
from bot.game.combat import power_score
from bot.game.economy import gold_payout
from bot.game.leveling import apply_xp
from bot.game.pve.ambient import AMBIENT_POOL, AmbientSpec
from bot.game.pve.combat import (
    DEFAULT_RESPAWN_SEC,
    PVE_WIN_PCT_BY_DIFF,
    RESPAWN_DURATION_SEC,
    WEAKNESS_BONUS_PCT,
    fail_gold_pct,
)
from bot.utils.embeds import info_embed

log = logging.getLogger(__name__)

AMBIENT_TTL = timedelta(minutes=5)


class AmbientView(discord.ui.View):
    """Persistent view — custom_ids encode the ambient event id."""

    def __init__(self, event_id: int | None = None):
        super().__init__(timeout=None)
        if event_id is not None:
            self.fight.custom_id = f"ambient:{event_id}:fight"   # type: ignore[attr-defined]
            self.run.custom_id = f"ambient:{event_id}:run"       # type: ignore[attr-defined]

    @discord.ui.button(label="Fight!", style=discord.ButtonStyle.success, emoji="⚔", custom_id="ambient:0:fight")
    async def fight(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _resolve_ambient(interaction, fled=False)

    @discord.ui.button(label="Run", style=discord.ButtonStyle.secondary, emoji="🏃", custom_id="ambient:0:run")
    async def run(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _resolve_ambient(interaction, fled=True)


def _parse_event_id(custom_id: str) -> int | None:
    parts = custom_id.split(":")
    if len(parts) >= 2 and parts[0] == "ambient":
        try:
            return int(parts[1])
        except ValueError:
            return None
    return None


async def _resolve_ambient(interaction: discord.Interaction, *, fled: bool) -> None:
    event_id = _parse_event_id(interaction.data.get("custom_id", ""))  # type: ignore[union-attr]
    if event_id is None:
        await interaction.response.send_message(
            embed=info_embed("This encounter has gone stale."), ephemeral=True
        )
        return

    event = await queries.get_ambient_event(event_id)
    if event is None or event.status != "pending":
        await interaction.response.send_message(
            embed=info_embed("This encounter is already resolved."), ephemeral=True
        )
        return

    if interaction.user.id != event.target_id:
        await interaction.response.send_message(
            "This encounter is not yours.", ephemeral=True
        )
        return

    spec = AMBIENT_POOL.get(event.event_type)
    if spec is None:
        await queries.resolve_ambient_event(event_id, "expired", 0, 0)
        await interaction.response.send_message(
            embed=info_embed("Encounter spec missing — resolved."), ephemeral=True
        )
        return

    user = await queries.get_user(interaction.user.id)

    if fled:
        # Small Gold penalty for running.
        penalty = max(10, int(spec.base_gold * 0.1))
        penalty = min(penalty, user.gold)
        await queries.add_gold(user.discord_id, -penalty)
        await queries.resolve_ambient_event(event_id, "fled", -penalty, 0)
        await interaction.response.edit_message(
            embed=info_embed(f"🏃 You flee from the **{spec.name}**. Lose {penalty}g for the trouble."),
            view=None,
        )
        return

    loadout = await queries.alive_loadout(user.discord_id)
    if not loadout:
        # No alive champ — auto-loss (treated as a matched-tier defeat).
        penalty = min(
            user.gold,
            max(10, int(
                gold_payout(spec.base_gold, user.level, user.prestige) * fail_gold_pct(0)
            )),
        )
        await queries.add_gold(user.discord_id, -penalty)
        await queries.resolve_ambient_event(event_id, "lost", -penalty, 0)
        await interaction.response.edit_message(
            embed=info_embed(f"💀 You have no alive champion. The **{spec.name}** drags you down for {penalty}g."),
            view=None,
        )
        return

    lead_entry = max(loadout, key=lambda e: power_score(e.champion))
    lead = lead_entry.champion

    # Same tier-diff win curve as camp combat, plus the champ ability bonus.
    diff = max(-4, min(4, lead.tier - spec.tier))
    win_pct = PVE_WIN_PCT_BY_DIFF[diff]
    if spec.weak_to and lead.damage_type == spec.weak_to:
        win_pct += WEAKNESS_BONUS_PCT
    win_pct += progress_win_bonus(lead_entry.progress)
    win_pct = max(1.0, min(99.0, win_pct))
    rng = random.Random()
    won = rng.uniform(0, 100) < win_pct

    if won:
        gold_reward = gold_payout(spec.base_gold, user.level, user.prestige)
        xp_result = apply_xp(user.xp, user.level, spec.base_xp)
        await queries.add_gold(user.discord_id, gold_reward)
        await queries.set_user_level_xp(user.discord_id, xp_result.new_level, xp_result.new_xp)
        await queries.resolve_ambient_event(event_id, "won", gold_reward, spec.base_xp)
        levelups = await award_champ_xp(
            user.discord_id, loadout, lead.id, AMBIENT_WIN_XP, EXPLORE_PASSIVE_SHARE
        )
        champ_line = ""
        if levelups:
            names = ", ".join(lu.champion.name for lu in levelups)
            champ_line = f"\n🆙 **{names}** levelled up — see `/champion`."
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"⚔ Victory — {spec.name}",
                description=(
                    f"**{lead.name}** dispatches the {spec.name}.\n"
                    f"Gold: **+{gold_reward:,}** · XP: **+{spec.base_xp}**"
                    + (f"\n:sparkles: **Level up → {xp_result.leveled_up_to}**" if xp_result.leveled_up_to else "")
                    + champ_line
                ),
                color=0x4CAF50,
            ),
            view=None,
        )
    else:
        # Loss — kill the champion. Level-scaled, tier-diff-scaled penalty.
        respawn = RESPAWN_DURATION_SEC.get(diff, DEFAULT_RESPAWN_SEC)
        penalty = min(
            user.gold,
            int(gold_payout(spec.base_gold, user.level, user.prestige) * fail_gold_pct(diff)),
        )
        await queries.add_gold(user.discord_id, -penalty)
        await queries.kill_champion(user.discord_id, lead.id, timedelta(seconds=respawn))
        await queries.resolve_ambient_event(event_id, "lost", -penalty, 0)
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"💀 Defeated by {spec.name}",
                description=(
                    f"**{lead.name}** fell to the {spec.name}.\n"
                    f"Gold lost: **{penalty}** · {lead.name} dies for **{respawn // 60} min**."
                ),
                color=0xF44336,
            ),
            view=None,
        )


class AmbientCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="ambient-toggle",
        description="Opt in or out of random ambient encounters (Gromp ambushes etc).",
    )
    async def ambient_toggle(self, interaction: discord.Interaction, opt_in: bool) -> None:
        await queries.ensure_user(interaction.user.id)
        await queries.set_ambient_opt_in(interaction.user.id, opt_in)
        msg = (
            "Ambient encounters **ON** — expect surprise mobs every ~20–40 min."
            if opt_in
            else "Ambient encounters **OFF** — you'll grind on your own time."
        )
        await interaction.response.send_message(embed=info_embed(msg), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    # Register persistent view so buttons survive restarts.
    bot.add_view(AmbientView())
    await bot.add_cog(AmbientCog(bot))
