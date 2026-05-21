"""Rolling cog — /roll, /roll10, /roll100, /roll1000, /redeem-fragment."""
from __future__ import annotations

import logging
import random
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.db.pool import get_pool
from bot.db.queries import Champion
from bot.game.economy import (
    FRAGMENT_THRESHOLDS,
    ROLL_COSTS,
    fragment_item_key,
)
from bot.game.rolling import (
    VALID_MULTIPLIERS,
    pick_champion_in_tier,
    roll_champion,
)
from bot.utils.decorators import register_user
from bot.utils.embeds import failure_embed, info_embed, pull_embed

log = logging.getLogger(__name__)


async def _champs_by_tier() -> dict[int, list[Champion]]:
    grouped: dict[int, list[Champion]] = defaultdict(list)
    for c in await queries.get_all_champions():
        grouped[c.tier].append(c)
    return grouped


async def _resolve_pull(
    roller_id: int,
    champion: Champion,
) -> tuple[Champion, bool, int | None, int | None]:
    """Persist a pull's outcome and return (final_owner_champ, was_dupe, fragment_qty_or_none, reap_diverted_to_or_none).

    Reap divert (PRD §6.7): if `roller_id` is marked and the pull is a champ the
    caster doesn't yet own, the caster gets the champion instead.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            mark = await queries.get_reap_mark(roller_id)
            if mark is not None:
                caster_id, _ = mark
                caster_owns = await conn.fetchval(
                    "SELECT 1 FROM user_champions WHERE user_id = $1 AND champion_id = $2",
                    caster_id, champion.id,
                )
                if not caster_owns:
                    # Divert: caster gains the champion. Roller loses the roll (no champ, no frag).
                    await queries.own_champion(caster_id, champion.id, conn=conn)
                    await queries.clear_reap_mark(roller_id, conn=conn)
                    return champion, False, None, caster_id
                # Caster already owns — fall through to normal resolution.

            newly_owned = await queries.own_champion(roller_id, champion.id, conn=conn)
            if newly_owned:
                return champion, False, None, None

            frag_key = fragment_item_key(champion.tier)
            new_qty = await queries.add_item(roller_id, frag_key, 1, conn=conn)
            return champion, True, new_qty, None


async def _do_roll(
    interaction: discord.Interaction,
    multiplier: int,
) -> None:
    user_id = interaction.user.id
    user = await queries.get_user(user_id)
    if user is None:
        user = await queries.ensure_user(user_id)

    pool = get_pool()
    cost = ROLL_COSTS[multiplier]
    # 1x rolls accept a Roll Token in lieu of gold.
    used_token = False
    if multiplier == 1:
        async with pool.acquire() as conn:
            async with conn.transaction():
                used_token = await queries.consume_item(user_id, "roll_token", 1, conn=conn)
                if not used_token:
                    if user.gold < cost:
                        await interaction.response.send_message(
                            embed=failure_embed(
                                f"Need {cost:,} Gold or 1 Roll Token. You have {user.gold:,} Gold."
                            ),
                            ephemeral=True,
                        )
                        return
                    await queries.add_gold(user_id, -cost, conn=conn)
    else:
        if user.gold < cost:
            await interaction.response.send_message(
                embed=failure_embed(
                    f"/roll{multiplier} costs {cost:,} Gold. You have {user.gold:,} Gold."
                ),
                ephemeral=True,
            )
            return
        await queries.add_gold(user_id, -cost)

    grouped = await _champs_by_tier()
    result = roll_champion(multiplier, grouped, prestige=user.prestige)

    final_champ, was_dupe, frag_qty, reap_to = await _resolve_pull(user_id, result.champion)

    if reap_to is not None:
        await interaction.response.send_message(
            embed=info_embed(
                f"You rolled **{final_champ.name}** — but Lamb walked beside you. "
                f"<@{reap_to}> reaped your pull."
            )
        )
        return

    embed = pull_embed(final_champ, was_dupe=was_dupe, fragment_qty=frag_qty)
    if used_token:
        embed.set_footer(text="Spent 1 Roll Token")
    elif multiplier > 1:
        embed.set_footer(text=f"/roll{multiplier} — guaranteed tier shifted up")
    await interaction.response.send_message(embed=embed)


class Rolling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="roll", description="Roll a champion. Spends a Roll Token if you have one, else Gold.")
    @register_user
    async def roll(self, interaction: discord.Interaction) -> None:
        await _do_roll(interaction, 1)

    @app_commands.command(name="roll10", description="10x roll — shifted odds, ≥ Tier 2 guaranteed.")
    @register_user
    async def roll10(self, interaction: discord.Interaction) -> None:
        await _do_roll(interaction, 10)

    @app_commands.command(name="roll100", description="100x roll — strong shift, ≥ Tier 3 guaranteed.")
    @register_user
    async def roll100(self, interaction: discord.Interaction) -> None:
        await _do_roll(interaction, 100)

    @app_commands.command(name="roll1000", description="1000x roll — big shift, ≥ Tier 4 guaranteed.")
    @register_user
    async def roll1000(self, interaction: discord.Interaction) -> None:
        await _do_roll(interaction, 1000)

    @app_commands.command(
        name="redeem-fragment",
        description="Spend fragments for a guaranteed pull at that tier.",
    )
    @app_commands.describe(tier="Tier 1–6 (no fragment path for Tier 7 Death).")
    @register_user
    async def redeem_fragment(self, interaction: discord.Interaction, tier: int) -> None:
        if tier not in FRAGMENT_THRESHOLDS:
            await interaction.response.send_message(
                embed=failure_embed("Tier must be between 1 and 6."), ephemeral=True
            )
            return

        threshold = FRAGMENT_THRESHOLDS[tier]
        item = fragment_item_key(tier)
        held = await queries.get_item_qty(interaction.user.id, item)
        if held < threshold:
            await interaction.response.send_message(
                embed=failure_embed(
                    f"Need {threshold} Tier {tier} fragments to redeem. You have {held}."
                ),
                ephemeral=True,
            )
            return

        # Spend, then guarantee a pick from that tier.
        pool = get_pool()
        candidates = await queries.list_champions_by_tier(tier)
        if not candidates:
            await interaction.response.send_message(
                embed=failure_embed("No champions seeded at that tier — contact admin."),
                ephemeral=True,
            )
            return

        rng = random.Random()
        picked = pick_champion_in_tier(candidates, rng=rng)

        async with pool.acquire() as conn:
            async with conn.transaction():
                ok = await queries.consume_item(interaction.user.id, item, threshold, conn=conn)
                if not ok:
                    await interaction.response.send_message(
                        embed=failure_embed("Fragment balance changed mid-redeem. Try again."),
                        ephemeral=True,
                    )
                    return

        final, was_dupe, frag_qty, reap_to = await _resolve_pull(interaction.user.id, picked)
        if reap_to is not None:
            await interaction.response.send_message(
                embed=info_embed(
                    f"You redeemed **{final.name}** — but Lamb walked beside you. "
                    f"<@{reap_to}> reaped your pull."
                )
            )
            return
        embed = pull_embed(final, was_dupe=was_dupe, fragment_qty=frag_qty)
        embed.set_footer(text=f"Spent {threshold} Tier {tier} fragments")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Rolling(bot))
