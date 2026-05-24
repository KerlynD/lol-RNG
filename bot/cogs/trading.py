"""Trading cog — single interactive `/trade @target` flow.

v3 replaces the old /trade + /accept + /decline + /cancel + /trades +
/trade-log set with one public embed both players interact with. Either
side can add or remove their own champions; the swap fires when both
sides hit Confirm. Multi-item offers are supported (3-for-1, 2-for-2,
etc) so trades can be made "fair" without forcing single-champ pairings.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.utils.decorators import register_user
from bot.utils.embeds import TIER_NAME, failure_embed, info_embed

TRADE_TTL = timedelta(hours=1)
log = logging.getLogger(__name__)


# ── Embed builders ──────────────────────────────────────────────────────────


def _format_items(items: list) -> str:
    if not items:
        return "_empty — add some champions_"
    return "\n".join(
        f"• **{c.name}** ({TIER_NAME[c.tier]})" for c in items
    )


def _trade_status_line(trade, ended: str | None = None) -> str:
    if ended:
        return f"Status: **{ended}**"
    parts = []
    parts.append("✅ confirmed" if trade.initiator_confirmed else "⏳ choosing")
    parts.append("✅ confirmed" if trade.target_confirmed else "⏳ choosing")
    return f"Initiator: {parts[0]}  ·  Target: {parts[1]}"


def trade_session_embed(
    trade,
    initiator: discord.abc.User,
    target: discord.abc.User,
    items_by_side: dict[str, list],
    ended: str | None = None,
) -> discord.Embed:
    color = 0x9C27B0
    if ended == "accepted":
        color = 0x4CAF50
    elif ended in ("cancelled", "expired"):
        color = 0xF44336
    embed = discord.Embed(
        title=f"🤝 Trade — {initiator.display_name} ↔ {target.display_name}",
        description=(
            f"**{initiator.display_name}** is offering:\n"
            f"{_format_items(items_by_side.get('initiator', []))}\n\n"
            f"**{target.display_name}** is offering:\n"
            f"{_format_items(items_by_side.get('target', []))}\n\n"
            f"{_trade_status_line(trade, ended)}"
        ),
        color=color,
    )
    if ended is None:
        embed.set_footer(
            text=(
                f"Trade #{trade.id} · expires <t:{int(trade.expires_at.timestamp())}:R>"
                "  ·  Either side: Add / Remove your own. Confirm when ready."
            )
        )
    return embed


# ── Interactive view + selects ──────────────────────────────────────────────


class TradeView(discord.ui.View):
    """The four-button view attached to the trade message itself."""

    def __init__(self, trade_id: int, initiator_id: int, target_id: int):
        super().__init__(timeout=TRADE_TTL.total_seconds())
        self.trade_id = trade_id
        self.initiator_id = initiator_id
        self.target_id = target_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.initiator_id, self.target_id):
            await interaction.response.send_message(
                "This isn't your trade.", ephemeral=True
            )
            return False
        return True

    def _side_for(self, user_id: int) -> str:
        return "initiator" if user_id == self.initiator_id else "target"

    @discord.ui.button(label="Add", emoji="➕", style=discord.ButtonStyle.success)
    async def add_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        side = self._side_for(interaction.user.id)
        owned = await queries.list_owned(interaction.user.id)
        items = await queries.list_trade_items(self.trade_id)
        in_trade = {c.id for c in items.get(side, [])}
        candidates = [oc for oc in owned if not oc.locked and oc.champion.id not in in_trade]
        if not candidates:
            await interaction.response.send_message(
                embed=failure_embed(
                    "No more champions to offer (all owned-and-unlocked are already on the table)."
                ),
                ephemeral=True,
            )
            return
        candidates.sort(key=lambda oc: (-oc.champion.tier, oc.champion.name))
        await interaction.response.send_message(
            content="Pick one to add to your side:",
            view=_AddPickerView(self, candidates[:25]),
            ephemeral=True,
        )

    @discord.ui.button(label="Remove", emoji="➖", style=discord.ButtonStyle.secondary)
    async def remove_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        side = self._side_for(interaction.user.id)
        items = await queries.list_trade_items(self.trade_id)
        my_items = items.get(side, [])
        if not my_items:
            await interaction.response.send_message(
                embed=info_embed("You have nothing on the table yet."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            content="Pick one to take back:",
            view=_RemovePickerView(self, my_items),
            ephemeral=True,
        )

    @discord.ui.button(label="Confirm", emoji="✅", style=discord.ButtonStyle.primary)
    async def confirm_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        side = self._side_for(interaction.user.id)
        items = await queries.list_trade_items(self.trade_id)
        if not items.get(side):
            await interaction.response.send_message(
                embed=failure_embed("Add at least one champion before confirming."),
                ephemeral=True,
            )
            return
        trade = await queries.set_trade_confirmed(self.trade_id, side, True)
        if trade is None:
            await interaction.response.send_message(
                embed=failure_embed("Trade is gone."), ephemeral=True
            )
            return
        if trade.initiator_confirmed and trade.target_confirmed:
            ok, reason = await queries.execute_trade_v2(self.trade_id)
            ended = "accepted" if ok else "cancelled"
            await self._rerender(interaction, ended=ended)
            self.stop()
            if not ok:
                await interaction.followup.send(
                    embed=failure_embed(f"Swap failed: {reason}"), ephemeral=True
                )
            return
        await self._rerender(interaction)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, _btn: discord.ui.Button) -> None:
        ok = await queries.cancel_trade(self.trade_id)
        if not ok:
            await interaction.response.send_message(
                embed=failure_embed("Trade is no longer active."), ephemeral=True
            )
            return
        await self._rerender(interaction, ended="cancelled")
        self.stop()

    async def _rerender(
        self, interaction: discord.Interaction, ended: str | None = None
    ) -> None:
        trade = await queries.get_trade(self.trade_id)
        items = await queries.list_trade_items(self.trade_id)
        initiator = interaction.guild.get_member(self.initiator_id) or await interaction.client.fetch_user(self.initiator_id)
        target = interaction.guild.get_member(self.target_id) or await interaction.client.fetch_user(self.target_id)
        if ended:
            for child in self.children:
                child.disabled = True  # type: ignore[attr-defined]
        embed = trade_session_embed(trade, initiator, target, items, ended=ended)
        view = None if ended else self
        await interaction.response.edit_message(embed=embed, view=view)


class _AddSelect(discord.ui.Select):
    def __init__(self, trade_view: "TradeView", owned_options: list):
        options = [
            discord.SelectOption(
                label=f"{oc.champion.name} ({TIER_NAME[oc.champion.tier]})"[:100],
                value=str(oc.champion.id),
            )
            for oc in owned_options
        ]
        super().__init__(
            placeholder="Champion to add…",
            options=options, min_values=1, max_values=1,
        )
        # NB: never assign `self._parent` — discord.py uses that name internally
        # to track the Select's owning View.
        self._trade_view = trade_view

    async def callback(self, interaction: discord.Interaction) -> None:
        champ_id = int(self.values[0])
        tv = self._trade_view
        side = tv._side_for(interaction.user.id)
        added = await queries.add_trade_item(tv.trade_id, side, champ_id)
        if not added:
            await interaction.response.edit_message(
                content="❌ Couldn't add — either the trade is no longer editable or the champion is already on your side.",
                view=None,
            )
            return
        await interaction.response.edit_message(content="✅ Added.", view=None)
        await _refresh_trade_message(interaction, tv)


class _RemoveSelect(discord.ui.Select):
    def __init__(self, trade_view: "TradeView", items: list):
        options = [
            discord.SelectOption(
                label=f"{c.name} ({TIER_NAME[c.tier]})"[:100],
                value=str(c.id),
            )
            for c in items[:25]
        ]
        super().__init__(
            placeholder="Champion to remove…",
            options=options, min_values=1, max_values=1,
        )
        self._trade_view = trade_view

    async def callback(self, interaction: discord.Interaction) -> None:
        champ_id = int(self.values[0])
        tv = self._trade_view
        side = tv._side_for(interaction.user.id)
        removed = await queries.remove_trade_item(tv.trade_id, side, champ_id)
        if not removed:
            await interaction.response.edit_message(
                content="❌ Couldn't remove — trade may already be confirmed.",
                view=None,
            )
            return
        await interaction.response.edit_message(content="✅ Removed.", view=None)
        await _refresh_trade_message(interaction, tv)


class _AddPickerView(discord.ui.View):
    def __init__(self, trade_view: "TradeView", owned_options: list):
        super().__init__(timeout=120.0)
        self.add_item(_AddSelect(trade_view, owned_options))


class _RemovePickerView(discord.ui.View):
    def __init__(self, trade_view: "TradeView", items: list):
        super().__init__(timeout=120.0)
        self.add_item(_RemoveSelect(trade_view, items))


async def _refresh_trade_message(interaction: discord.Interaction, parent: "TradeView") -> None:
    """Edit the public trade message after an ephemeral picker action."""
    trade = await queries.get_trade(parent.trade_id)
    if trade is None or trade.message_id is None or trade.channel_id is None:
        return
    items = await queries.list_trade_items(parent.trade_id)
    initiator = interaction.guild.get_member(parent.initiator_id) or await interaction.client.fetch_user(parent.initiator_id)
    target = interaction.guild.get_member(parent.target_id) or await interaction.client.fetch_user(parent.target_id)
    embed = trade_session_embed(trade, initiator, target, items)
    channel = interaction.client.get_channel(trade.channel_id)
    if channel is None:
        return
    try:
        msg = await channel.fetch_message(trade.message_id)
        await msg.edit(embed=embed, view=parent)
    except discord.HTTPException:
        log.exception("Failed to refresh trade message")


# ── Cog ──────────────────────────────────────────────────────────────────────


class Trading(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="trade",
        description="Open an interactive trade — both players add champions and confirm.",
    )
    @app_commands.describe(target="The user you want to trade with.")
    @register_user
    async def trade(
        self, interaction: discord.Interaction, target: discord.Member
    ) -> None:
        if target.bot or target.id == interaction.user.id:
            await interaction.response.send_message(
                embed=failure_embed("Invalid trade target."), ephemeral=True
            )
            return
        await queries.ensure_user(target.id)

        trade = await queries.create_trade_session(
            initiator_id=interaction.user.id,
            target_id=target.id,
            ttl=TRADE_TTL,
        )
        items = {"initiator": [], "target": []}
        view = TradeView(trade.id, interaction.user.id, target.id)
        embed = trade_session_embed(trade, interaction.user, target, items)
        await interaction.response.send_message(
            content=f"{target.mention} — {interaction.user.mention} wants to trade.",
            embed=embed,
            view=view,
        )
        msg = await interaction.original_response()
        await queries.set_trade_message(trade.id, msg.channel.id, msg.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Trading(bot))
