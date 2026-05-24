"""God-tier (T6) and Death-tier (T7) actions.

Separate cog because these have unique side effects beyond gold/xp/drops
that the generic action runner doesn't handle. Each command first calls
run_action to enforce the cooldown + required champion + grant XP, then
layers the special side effect (reap mark, immunity, etc.) on top.
"""
from __future__ import annotations

import logging
import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.db.pool import get_pool
from bot.game.actions.registry import ACTIONS
from bot.game.actions.runner import ActionFailure, ActionSuccess, run_action
from bot.game.economy import fragment_item_key
from bot.game.pvp_flow import (
    LAMBS_RESPITE_COOLDOWN_KEY,
    WORLD_ENDER_COOLDOWN_KEY,
)
from bot.game.rolling import pick_champion_in_tier
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    TIER_COLOR,
    action_result_embed,
    cooldown_embed,
    failure_embed,
    pull_embed,
)

log = logging.getLogger(__name__)

WORLD_ENDER_DURATION = timedelta(hours=24)
LAMBS_RESPITE_DURATION = timedelta(hours=72)
ETERNAL_HUNT_DURATION = timedelta(days=7)
REAP_MARK_DURATION = timedelta(days=7)


async def _gate_action(
    interaction: discord.Interaction, key: str
) -> ActionSuccess | None:
    user = await queries.get_user(interaction.user.id)
    result = await run_action(user, key)
    if isinstance(result, ActionFailure):
        spec = ACTIONS[key]
        if result.seconds_remaining is not None:
            await interaction.response.send_message(
                embed=cooldown_embed(spec.name, result.seconds_remaining), ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=failure_embed(result.reason), ephemeral=True
            )
        return None
    return result


class Godlike(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ===== God (T6) =========================================================

    @app_commands.command(
        name="reshape-stars",
        description=ACTIONS["reshape-stars"].description,
    )
    @app_commands.describe(champion="A champion you own — re-rolled within same tier.")
    @register_user
    async def reshape_stars(self, interaction: discord.Interaction, champion: str) -> None:
        target = await queries.get_champion_by_name(champion)
        if target is None or not await queries.owns_champion(interaction.user.id, target.id):
            await interaction.response.send_message(
                embed=failure_embed(f"You don't own **{champion}**."), ephemeral=True
            )
            return
        if await queries.is_locked(interaction.user.id, target.id):
            await interaction.response.send_message(
                embed=failure_embed(f"**{target.name}** is locked."), ephemeral=True
            )
            return

        success = await _gate_action(interaction, "reshape-stars")
        if success is None:
            return

        candidates = [
            c for c in await queries.list_champions_by_tier(target.tier)
            if c.id != target.id
        ]
        if not candidates:
            await interaction.response.send_message(
                embed=failure_embed("No alternate champions available at this tier."),
                ephemeral=True,
            )
            return
        rng = random.Random()
        rolled = pick_champion_in_tier(candidates, rng=rng)

        pool = get_pool()
        was_dupe = False
        frag_qty: int | None = None
        async with pool.acquire() as conn:
            async with conn.transaction():
                await queries.remove_champion(interaction.user.id, target.id, conn=conn)
                newly = await queries.own_champion(interaction.user.id, rolled.id, conn=conn)
                if not newly:
                    was_dupe = True
                    frag_key = fragment_item_key(rolled.tier)
                    frag_qty = await queries.add_item(interaction.user.id, frag_key, 1, conn=conn)

        embed = pull_embed(rolled, was_dupe=was_dupe, fragment_qty=frag_qty)
        embed.title = f"⭐ Reshape the Stars — {target.name} → {rolled.name}"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="world-ender", description=ACTIONS["world-ender"].description)
    @register_user
    async def world_ender(self, interaction: discord.Interaction) -> None:
        success = await _gate_action(interaction, "world-ender")
        if success is None:
            return
        await queries.set_cooldown(
            interaction.user.id, WORLD_ENDER_COOLDOWN_KEY, WORLD_ENDER_DURATION
        )
        embed = action_result_embed(success)
        embed.title = "🩸 World Ender"
        embed.description += "\n\n_Your PvP wins pay double for 24h. You may also be attacked beyond the daily cap._"
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="wander", description=ACTIONS["wander"].description)
    @app_commands.describe(action_key="The action key to execute for free (T1–T4).")
    @register_user
    async def wander(self, interaction: discord.Interaction, action_key: str) -> None:
        spec = ACTIONS.get(action_key)
        if spec is None or spec.tier < 1 or spec.tier > 4:
            await interaction.response.send_message(
                embed=failure_embed("Wander only works on T1–T4 actions. Use the action's key (e.g. `forage`)."),
                ephemeral=True,
            )
            return

        success = await _gate_action(interaction, "wander")
        if success is None:
            return

        # Run the target action, bypassing cooldown + requirements check.
        # Note: requirement checks (region/faction) still apply — we don't override those.
        user = await queries.get_user(interaction.user.id)
        inner = await run_action(user, action_key, bypass_cooldown=True)
        if isinstance(inner, ActionFailure):
            await interaction.followup.send(
                embed=failure_embed(f"Inner action failed: {inner.reason}")
            )
            return
        await interaction.response.send_message(
            embed=action_result_embed(success)
        )
        await interaction.followup.send(embed=action_result_embed(inner))

    @app_commands.command(name="portal", description=ACTIONS["portal"].description)
    @app_commands.describe(
        target="Who to swap with.",
        offer="The champion you'd give up.",
        request="The champion you want.",
    )
    @register_user
    async def portal(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        offer: str,
        request: str,
    ) -> None:
        if target.bot or target.id == interaction.user.id:
            await interaction.response.send_message(
                embed=failure_embed("Invalid target."), ephemeral=True
            )
            return
        offered = await queries.get_champion_by_name(offer)
        requested = await queries.get_champion_by_name(request)
        if offered is None or requested is None:
            await interaction.response.send_message(
                embed=failure_embed("Invalid champion name."), ephemeral=True
            )
            return
        if offered.tier != requested.tier:
            await interaction.response.send_message(
                embed=failure_embed("Portal requires same-tier champions."),
                ephemeral=True,
            )
            return

        # Open an interactive trade session pre-populated with the two champs;
        # both sides just need to hit Confirm.
        success = await _gate_action(interaction, "portal")
        if success is None:
            return

        if not await queries.owns_champion(interaction.user.id, offered.id):
            await interaction.followup.send(
                embed=failure_embed(f"You don't own **{offered.name}**.")
            )
            return
        await queries.ensure_user(target.id)
        if not await queries.owns_champion(target.id, requested.id):
            await interaction.followup.send(
                embed=failure_embed(f"{target.display_name} doesn't own **{requested.name}**.")
            )
            return

        from bot.cogs.trading import TRADE_TTL, TradeView, trade_session_embed

        trade = await queries.create_trade_session(
            initiator_id=interaction.user.id,
            target_id=target.id,
            ttl=TRADE_TTL,
        )
        await queries.add_trade_item(trade.id, "initiator", offered.id)
        await queries.add_trade_item(trade.id, "target", requested.id)
        items = await queries.list_trade_items(trade.id)
        view = TradeView(trade.id, interaction.user.id, target.id)
        embed = trade_session_embed(trade, interaction.user, target, items)
        embed.title = f"🌀 Portal — {embed.title.replace('🤝 Trade — ', '')}"
        await interaction.followup.send(
            content=f"{target.mention} — {interaction.user.mention} opened a Portal.",
            embed=embed,
            view=view,
        )
        msg = await interaction.original_response()
        await queries.set_trade_message(trade.id, msg.channel.id, msg.id)

    # ===== Death (T7) ========================================================

    @app_commands.command(name="reap", description=ACTIONS["reap"].description)
    @app_commands.describe(target="Who to mark.")
    @register_user
    async def reap(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if target.bot or target.id == interaction.user.id:
            await interaction.response.send_message(
                embed=failure_embed("Invalid target."), ephemeral=True
            )
            return

        success = await _gate_action(interaction, "reap")
        if success is None:
            return

        marked = await queries.set_reap_mark(
            target_id=target.id, caster_id=interaction.user.id, ttl=REAP_MARK_DURATION
        )
        if not marked:
            # Refund the cooldown — exclusive collision is a known PRD failure mode.
            await queries.clear_cooldown(interaction.user.id, "reap")
            await interaction.response.send_message(
                embed=failure_embed("Lamb already walks beside them.")
            )
            return

        embed = discord.Embed(
            title="💀 Reap",
            description=(
                f"You mark **{target.display_name}**. Their next unique pull "
                f"diverts to you. (7 days)"
            ),
            color=TIER_COLOR[7],
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="lambs-respite", description=ACTIONS["lambs-respite"].description)
    @register_user
    async def lambs_respite(self, interaction: discord.Interaction) -> None:
        success = await _gate_action(interaction, "lambs-respite")
        if success is None:
            return
        await queries.set_cooldown(
            interaction.user.id, LAMBS_RESPITE_COOLDOWN_KEY, LAMBS_RESPITE_DURATION
        )
        embed = discord.Embed(
            title="🌿 Lamb's Respite",
            description="You are wreathed in Lamb's Respite. **72 hours of total PvP immunity.**",
            color=TIER_COLOR[7],
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="eternal-hunt", description=ACTIONS["eternal-hunt"].description)
    @app_commands.describe(target="Who to hunt.")
    @register_user
    async def eternal_hunt(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if target.bot or target.id == interaction.user.id:
            await interaction.response.send_message(
                embed=failure_embed("Invalid target."), ephemeral=True
            )
            return
        success = await _gate_action(interaction, "eternal-hunt")
        if success is None:
            return
        await queries.set_cooldown(
            interaction.user.id, f"_hunt:{target.id}", ETERNAL_HUNT_DURATION
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🐺 Eternal Hunt",
                description=(
                    f"Wolf marks **{target.display_name}**. "
                    f"Use `/spy {target.display_name}` for the next 7 days."
                ),
                color=TIER_COLOR[7],
            )
        )

    @app_commands.command(
        name="never-one-without-the-other",
        description=ACTIONS["never-one-without-the-other"].description,
    )
    @register_user
    async def never_one(self, interaction: discord.Interaction) -> None:
        # The kindred_passive item is granted by the action's drop_table.
        success = await _gate_action(interaction, "never-one-without-the-other")
        if success is None:
            return
        await interaction.response.send_message(
            embed=discord.Embed(
                title="🏹 Never One Without the Other",
                description=(
                    "A shard of Wolf clings to you. **The next incoming PvP attempt "
                    "against you will end in a forced tie.**"
                ),
                color=TIER_COLOR[7],
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Godlike(bot))
