"""Trading cog — /trade, /accept, /decline, /cancel, /trades, /trade-log."""
from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.db.pool import get_pool
from bot.game.economy import TRADE_TAX_GOLD
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    TIER_NAME,
    failure_embed,
    info_embed,
    trade_embed,
)

TRADE_TTL = timedelta(hours=1)
log = logging.getLogger(__name__)


async def _autocomplete_owned(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    owned = await queries.list_owned(interaction.user.id)
    needle = (current or "").lower()
    return [
        app_commands.Choice(name=oc.champion.name, value=oc.champion.name)
        for oc in owned if needle in oc.champion.name.lower()
    ][:25]


class Trading(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="trade", description=f"Offer a trade. Flat {TRADE_TAX_GOLD} Gold tax.")
    @app_commands.describe(
        target="The user you want to trade with.",
        offer="Your champion you'd give up.",
        request="Their champion you want.",
    )
    @app_commands.autocomplete(offer=_autocomplete_owned)
    @register_user
    async def trade(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        offer: str,
        request: str,
    ) -> None:
        if target.bot or target.id == interaction.user.id:
            await interaction.response.send_message(
                embed=failure_embed("Invalid trade target."), ephemeral=True
            )
            return

        offered = await queries.get_champion_by_name(offer)
        requested = await queries.get_champion_by_name(request)
        if offered is None:
            await interaction.response.send_message(
                embed=failure_embed(f"No champion named **{offer}**."), ephemeral=True
            )
            return
        if requested is None:
            await interaction.response.send_message(
                embed=failure_embed(f"No champion named **{request}**."), ephemeral=True
            )
            return

        if not await queries.owns_champion(interaction.user.id, offered.id):
            await interaction.response.send_message(
                embed=failure_embed(f"You don't own **{offered.name}**."), ephemeral=True
            )
            return
        if await queries.is_locked(interaction.user.id, offered.id):
            await interaction.response.send_message(
                embed=failure_embed(f"**{offered.name}** is locked."), ephemeral=True
            )
            return

        await queries.ensure_user(target.id)
        if not await queries.owns_champion(target.id, requested.id):
            await interaction.response.send_message(
                embed=failure_embed(f"{target.display_name} doesn't own **{requested.name}**."),
                ephemeral=True,
            )
            return

        initiator = await queries.get_user(interaction.user.id)
        if initiator.gold < TRADE_TAX_GOLD:
            await interaction.response.send_message(
                embed=failure_embed(
                    f"Need {TRADE_TAX_GOLD:,} Gold tax. You have {initiator.gold:,}."
                ),
                ephemeral=True,
            )
            return

        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await queries.add_gold(interaction.user.id, -TRADE_TAX_GOLD, conn=conn)
        trade_row = await queries.create_trade(
            initiator_id=interaction.user.id,
            target_id=target.id,
            offered_champion_id=offered.id,
            requested_champion_id=requested.id,
            ttl=TRADE_TTL,
        )

        embed = trade_embed(trade_row, offered, requested)
        embed.set_footer(text=f"Tax {TRADE_TAX_GOLD} Gold paid. {target.display_name} has 1h to /accept.")
        await interaction.response.send_message(content=target.mention, embed=embed)

    @app_commands.command(name="accept", description="Accept a pending trade by ID.")
    @register_user
    async def accept(self, interaction: discord.Interaction, trade_id: int) -> None:
        trade = await queries.get_trade(trade_id)
        if trade is None or trade.target_id != interaction.user.id:
            await interaction.response.send_message(
                embed=failure_embed("That trade isn't yours to accept."), ephemeral=True
            )
            return
        if trade.status != "pending":
            await interaction.response.send_message(
                embed=failure_embed(f"Trade #{trade_id} is `{trade.status}`."), ephemeral=True
            )
            return

        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Re-validate inside the transaction.
                initiator_owns = await conn.fetchval(
                    "SELECT 1 FROM user_champions WHERE user_id = $1 AND champion_id = $2",
                    trade.initiator_id, trade.offered_champion_id,
                )
                target_owns = await conn.fetchval(
                    "SELECT 1 FROM user_champions WHERE user_id = $1 AND champion_id = $2",
                    trade.target_id, trade.requested_champion_id,
                )
                initiator_locked = await conn.fetchval(
                    "SELECT locked FROM user_champions WHERE user_id = $1 AND champion_id = $2",
                    trade.initiator_id, trade.offered_champion_id,
                )
                target_locked = await conn.fetchval(
                    "SELECT locked FROM user_champions WHERE user_id = $1 AND champion_id = $2",
                    trade.target_id, trade.requested_champion_id,
                )

                if not initiator_owns or not target_owns:
                    await queries.set_trade_status(trade_id, "cancelled", conn=conn)
                    await interaction.response.send_message(
                        embed=failure_embed("One side no longer owns the traded champion."),
                        ephemeral=True,
                    )
                    return
                if initiator_locked or target_locked:
                    await queries.set_trade_status(trade_id, "cancelled", conn=conn)
                    await interaction.response.send_message(
                        embed=failure_embed("One side has the champion locked."),
                        ephemeral=True,
                    )
                    return

                # Atomic swap
                await queries.remove_champion(trade.initiator_id, trade.offered_champion_id, conn=conn)
                await queries.own_champion(trade.target_id, trade.offered_champion_id, conn=conn)
                await queries.remove_champion(trade.target_id, trade.requested_champion_id, conn=conn)
                await queries.own_champion(trade.initiator_id, trade.requested_champion_id, conn=conn)
                await queries.set_trade_status(trade_id, "accepted", conn=conn)

        await interaction.response.send_message(
            embed=info_embed(f"Trade #{trade_id} accepted. Champions swapped.")
        )

    @app_commands.command(name="decline", description="Decline a pending trade by ID.")
    @register_user
    async def decline(self, interaction: discord.Interaction, trade_id: int) -> None:
        trade = await queries.get_trade(trade_id)
        if trade is None or trade.target_id != interaction.user.id:
            await interaction.response.send_message(
                embed=failure_embed("That trade isn't yours to decline."), ephemeral=True
            )
            return
        if trade.status != "pending":
            await interaction.response.send_message(
                embed=failure_embed(f"Trade #{trade_id} is `{trade.status}`."), ephemeral=True
            )
            return

        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await queries.set_trade_status(trade_id, "declined", conn=conn)
                # Refund tax
                await queries.add_gold(trade.initiator_id, TRADE_TAX_GOLD, conn=conn)
        await interaction.response.send_message(
            embed=info_embed(f"Trade #{trade_id} declined. Tax refunded to <@{trade.initiator_id}>.")
        )

    @app_commands.command(name="cancel", description="Cancel a trade you initiated.")
    @register_user
    async def cancel(self, interaction: discord.Interaction, trade_id: int) -> None:
        trade = await queries.get_trade(trade_id)
        if trade is None or trade.initiator_id != interaction.user.id:
            await interaction.response.send_message(
                embed=failure_embed("That trade isn't yours to cancel."), ephemeral=True
            )
            return
        if trade.status != "pending":
            await interaction.response.send_message(
                embed=failure_embed(f"Trade #{trade_id} is `{trade.status}`."), ephemeral=True
            )
            return

        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await queries.set_trade_status(trade_id, "cancelled", conn=conn)
                await queries.add_gold(interaction.user.id, TRADE_TAX_GOLD, conn=conn)
        await interaction.response.send_message(
            embed=info_embed(f"Trade #{trade_id} cancelled. Tax refunded.")
        )

    @app_commands.command(name="trades", description="List your pending trades.")
    @register_user
    async def trades(self, interaction: discord.Interaction) -> None:
        rows = await queries.list_pending_trades_for_user(interaction.user.id)
        if not rows:
            await interaction.response.send_message(
                embed=info_embed("No pending trades."), ephemeral=True
            )
            return
        lines = []
        for t in rows:
            offered = await queries.get_champion_by_id(t.offered_champion_id)
            requested = await queries.get_champion_by_id(t.requested_champion_id)
            direction = "→ you" if t.target_id == interaction.user.id else "← you initiated"
            lines.append(
                f"**#{t.id}** {direction}\n"
                f"  Offer: {offered.name} ({TIER_NAME[offered.tier]})\n"
                f"  Want:  {requested.name} ({TIER_NAME[requested.tier]})\n"
                f"  Expires: <t:{int(t.expires_at.timestamp())}:R>"
            )
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Pending trades",
                description="\n\n".join(lines),
                color=0x9C27B0,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="trade-log", description="View recent trade history.")
    @app_commands.describe(user="Optional — view someone else's history.")
    @register_user
    async def trade_log(
        self, interaction: discord.Interaction, user: discord.Member | None = None
    ) -> None:
        target_id = user.id if user else interaction.user.id
        rows = await queries.list_trade_log(target_id)
        if not rows:
            await interaction.response.send_message(
                embed=info_embed("No trade history."), ephemeral=True
            )
            return
        lines = []
        for t in rows:
            offered = await queries.get_champion_by_id(t.offered_champion_id)
            requested = await queries.get_champion_by_id(t.requested_champion_id)
            lines.append(
                f"#{t.id} [{t.status}] {offered.name} ↔ {requested.name} "
                f"(<t:{int(t.created_at.timestamp())}:R>)"
            )
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"Trade log — {user.display_name if user else 'you'}",
                description="\n".join(lines),
                color=0x9C27B0,
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Trading(bot))
