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
    pick_champion_in_tier,
    roll_champion,
)
from bot.game.world.regions import get_region, roll_tier_cap
from bot.utils.decorators import register_user
from bot.utils.embeds import TIER_NAME, failure_embed, info_embed, pull_embed


def _region_cap_footer(region_key: str | None) -> str | None:
    """Footer text noting the region roll cap, or None if uncapped (T7)."""
    cap = roll_tier_cap(region_key)
    if cap >= 7:
        return None
    region = get_region(region_key)
    where = region.display if region else "your region"
    return f"Rolls here cap at {TIER_NAME[cap]} (T{cap}) — {where}. Travel onward for higher tiers."

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


async def _do_single_roll(interaction: discord.Interaction) -> None:
    """The classic /roll — one pull, spends a Roll Token if available, else Gold."""
    user_id = interaction.user.id
    user = await queries.get_user(user_id)
    if user is None:
        user = await queries.ensure_user(user_id)

    pool = get_pool()
    cost = ROLL_COSTS[1]
    used_token = False
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

    grouped = await _champs_by_tier()
    cap = roll_tier_cap(user.current_region)
    result = roll_champion(1, grouped, prestige=user.prestige, max_tier=cap)
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
    footer_parts = []
    if used_token:
        footer_parts.append("Spent 1 Roll Token")
    cap_note = _region_cap_footer(user.current_region)
    if cap_note:
        footer_parts.append(cap_note)
    if footer_parts:
        embed.set_footer(text="  •  ".join(footer_parts))
    await interaction.response.send_message(embed=embed)


async def _do_bulk_rolls(interaction: discord.Interaction, n: int) -> None:
    """N independent pulls at base odds. Cost = N * base. Combined summary embed.

    Each pull is fully independent — same probability table as /roll. Multipliers
    no longer shift tier weights; they just buy you more pulls.
    """
    user_id = interaction.user.id
    user = await queries.get_user(user_id)
    if user is None:
        user = await queries.ensure_user(user_id)

    cost = ROLL_COSTS[1] * n
    if user.gold < cost:
        await interaction.response.send_message(
            embed=failure_embed(
                f"/roll{n} costs {cost:,} Gold ({n} × {ROLL_COSTS[1]:,}). You have {user.gold:,}."
            ),
            ephemeral=True,
        )
        return

    # Defer because 100+ pulls can take a few seconds.
    await interaction.response.defer()

    await queries.add_gold(user_id, -cost)
    grouped = await _champs_by_tier()

    new_champs: list[Champion] = []
    dupe_champs: list[Champion] = []
    dupe_by_tier: dict[int, int] = {}
    reaped: list[tuple[Champion, int]] = []   # (champ, caster_id)
    all_pulled: list[Champion] = []

    cap = roll_tier_cap(user.current_region)
    rng = random.Random()
    for _ in range(n):
        result = roll_champion(1, grouped, prestige=user.prestige, rng=rng, max_tier=cap)
        champ, was_dupe, _frag_qty, reap_to = await _resolve_pull(user_id, result.champion)
        all_pulled.append(champ)
        if reap_to is not None:
            reaped.append((champ, reap_to))
        elif was_dupe:
            dupe_champs.append(champ)
            dupe_by_tier[champ.tier] = dupe_by_tier.get(champ.tier, 0) + 1
        else:
            new_champs.append(champ)

    embed = _bulk_roll_summary_embed(n, cost, new_champs, dupe_by_tier, reaped, all_pulled)
    cap_note = _region_cap_footer(user.current_region)
    if cap_note:
        embed.set_footer(text=cap_note)
    await interaction.followup.send(embed=embed)


def _bulk_roll_summary_embed(
    n: int,
    cost: int,
    new_champs: list[Champion],
    dupe_by_tier: dict[int, int],
    reaped: list[tuple[Champion, int]],
    all_pulled: list[Champion],
) -> discord.Embed:
    # Pick the highest-tier overall pull for the headline splash (new OR dupe).
    highlight: Champion | None = (
        max(all_pulled, key=lambda c: c.tier) if all_pulled else None
    )
    headline_tier = highlight.tier if highlight else 1
    embed = discord.Embed(
        title=f"🎲 {n} Rolls",
        description=f"Spent **{cost:,} Gold**"
        + (
            f"\n\n✨ Highlight pull: **{highlight.name}** ({TIER_NAME[highlight.tier]})"
            if highlight else ""
        ),
        color=_TIER_COLORS.get(headline_tier, 0x607D8B),
    )
    if highlight and highlight.splash_url:
        embed.set_image(url=highlight.splash_url)

    if new_champs:
        # Sort by tier desc, then name.
        new_champs.sort(key=lambda c: (-c.tier, c.name))
        lines: list[str] = []
        for c in new_champs[:25]:
            label = f"**{c.name}** (T{c.tier}{', ' + c.region if c.region else ''})"
            if c.tier >= 6:
                label += " 🌟"
            lines.append("• " + label)
        if len(new_champs) > 25:
            lines.append(f"_…and {len(new_champs) - 25} more new pulls_")
        embed.add_field(
            name=f"✨ New champions ({len(new_champs)})",
            value="\n".join(lines)[:1024],
            inline=False,
        )

    if dupe_by_tier:
        lines = [
            f"  {TIER_NAME[t]}: ×{q}"
            for t, q in sorted(dupe_by_tier.items(), reverse=True)
        ]
        total_dupes = sum(dupe_by_tier.values())
        embed.add_field(
            name=f"🧩 Fragments earned ({total_dupes} dupes)",
            value="\n".join(lines),
            inline=False,
        )

    if reaped:
        lines = [
            f"  **{c.name}** (T{c.tier}) → <@{caster_id}>"
            for c, caster_id in reaped[:5]
        ]
        if len(reaped) > 5:
            lines.append(f"  _…and {len(reaped) - 5} more_")
        embed.add_field(
            name=f"💀 Reaped ({len(reaped)})",
            value="\n".join(lines),
            inline=False,
        )

    if not new_champs and not dupe_by_tier and not reaped:
        embed.add_field(name="—", value="_Nothing? That shouldn't happen._", inline=False)

    return embed


_TIER_COLORS = {
    1: 0x9E9E9E, 2: 0x4CAF50, 3: 0x2196F3, 4: 0x9C27B0,
    5: 0xFFC107, 6: 0xFF5722, 7: 0x000000,
}


class Rolling(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="roll", description="Roll a champion. Spends a Roll Token if you have one, else Gold.")
    @register_user
    async def roll(self, interaction: discord.Interaction) -> None:
        await _do_single_roll(interaction)

    @app_commands.command(name="roll10", description="10 rolls at base odds. Cost: 10× base.")
    @register_user
    async def roll10(self, interaction: discord.Interaction) -> None:
        await _do_bulk_rolls(interaction, 10)

    @app_commands.command(name="roll100", description="100 rolls at base odds. Cost: 100× base.")
    @register_user
    async def roll100(self, interaction: discord.Interaction) -> None:
        await _do_bulk_rolls(interaction, 100)

    @app_commands.command(name="roll1000", description="1000 rolls at base odds. Cost: 1000× base. Big spender mode.")
    @register_user
    async def roll1000(self, interaction: discord.Interaction) -> None:
        await _do_bulk_rolls(interaction, 1000)

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

        # Region roll cap also applies to fragment redemption.
        user = await queries.get_user(interaction.user.id)
        cap = roll_tier_cap(user.current_region if user else None)
        if tier > cap:
            region = get_region(user.current_region if user else None)
            where = region.display if region else "this region"
            await interaction.response.send_message(
                embed=failure_embed(
                    f"You can only redeem up to **{TIER_NAME[cap]}** fragments in "
                    f"**{where}**. Travel onward to redeem Tier {tier}."
                ),
                ephemeral=True,
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
