"""Inventory cog — /inventory, /profile, /shields.

The /inventory embed has Activate buttons for red_buff / blue_buff so
players can prime them on demand before a big fight. Buffs are inert
until primed.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.db.pool import get_pool
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    failure_embed,
    info_embed,
    inventory_embed,
    profile_embed,
)


def _fmt_revive(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}m {s % 60}s" if s >= 60 else f"{s}s"


class _ReviveSelect(discord.ui.Select):
    def __init__(self, owner_id: int, dead: list[tuple[int, str, float]]):
        self.owner_id = owner_id
        self._names = {str(cid): name for cid, name, _ in dead}
        options = [
            discord.SelectOption(
                label=name[:100],
                value=str(cid),
                description=f"Revives in {_fmt_revive(secs)}"[:100],
            )
            for cid, name, secs in dead[:25]
        ]
        super().__init__(
            placeholder="Pick a champion to revive…",
            options=options, min_values=1, max_values=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        champ_id = int(self.values[0])
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                ok = await queries.consume_item(
                    self.owner_id, "revive_potion", 1, conn=conn
                )
                if not ok:
                    await interaction.response.edit_message(
                        embed=failure_embed("You have no revive potions left."),
                        view=None,
                    )
                    return
                await queries.revive_champion(self.owner_id, champ_id, conn=conn)
        name = self._names.get(self.values[0], "Your champion")
        await interaction.response.edit_message(
            embed=info_embed(f"🧪 **{name}** is revived and ready to fight again!"),
            view=None,
        )


class ReviveSelectView(discord.ui.View):
    def __init__(self, owner_id: int, dead: list[tuple[int, str, float]]):
        super().__init__(timeout=120.0)
        self.owner_id = owner_id
        self.add_item(_ReviveSelect(owner_id, dead))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your inventory.", ephemeral=True
            )
            return False
        return True


class InventoryView(discord.ui.View):
    """Interactive controls on /inventory. Lifetime = 3 min."""

    def __init__(self, owner_id: int, inventory: dict[str, int]):
        super().__init__(timeout=180.0)
        self.owner_id = owner_id
        self._refresh_buttons(inventory)

    def _refresh_buttons(self, inventory: dict[str, int]) -> None:
        red_dormant = inventory.get("red_buff", 0)
        red_primed = inventory.get("red_buff_primed", 0)
        blue_dormant = inventory.get("blue_buff", 0)
        blue_primed = inventory.get("blue_buff_primed", 0)

        self.activate_red.label = (
            f"Prime Red Buff ({red_dormant})" if red_dormant else "No Red Buff"
        )
        self.activate_red.disabled = red_dormant <= 0

        self.activate_blue.label = (
            f"Prime Blue Buff ({blue_dormant})" if blue_dormant else "No Blue Buff"
        )
        self.activate_blue.disabled = blue_dormant <= 0

        revive = inventory.get("revive_potion", 0)
        self.use_revive.label = (
            f"Use Revive Potion ({revive})" if revive else "No Revive Potion"
        )
        self.use_revive.disabled = revive <= 0

        # Show primed state as labels on disabled "info" buttons would be too
        # noisy. We surface the primed count in the embed itself.
        _ = (red_primed, blue_primed)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your inventory.", ephemeral=True
            )
            return False
        return True

    async def _activate(
        self, interaction: discord.Interaction, dormant_key: str, primed_key: str
    ) -> None:
        # Atomically move one dormant → primed.
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                ok = await queries.consume_item(self.owner_id, dormant_key, 1, conn=conn)
                if not ok:
                    await interaction.response.send_message(
                        "You don't have that buff anymore.", ephemeral=True
                    )
                    return
                await queries.add_item(self.owner_id, primed_key, 1, conn=conn)

        # Refresh the embed in place.
        new_inv = await queries.get_inventory(self.owner_id)
        user = await queries.get_user(self.owner_id)
        embed = inventory_embed(new_inv)
        embed.add_field(name="Gold", value=f"{user.gold:,}", inline=True)
        self._refresh_buttons(new_inv)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="Prime Red Buff", style=discord.ButtonStyle.danger, emoji="🔴"
    )
    async def activate_red(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._activate(interaction, "red_buff", "red_buff_primed")

    @discord.ui.button(
        label="Prime Blue Buff", style=discord.ButtonStyle.primary, emoji="🔵"
    )
    async def activate_blue(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self._activate(interaction, "blue_buff", "blue_buff_primed")

    @discord.ui.button(
        label="Use Revive Potion", style=discord.ButtonStyle.success, emoji="🧪"
    )
    async def use_revive(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        qty = (await queries.get_inventory(self.owner_id)).get("revive_potion", 0)
        if qty <= 0:
            await interaction.response.send_message(
                embed=failure_embed("You have no revive potions."), ephemeral=True
            )
            return
        dead = await queries.dead_champions_for_user(self.owner_id)
        if not dead:
            await interaction.response.send_message(
                embed=info_embed("None of your loadout champions are dead."),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=info_embed("Pick a champion to bring back to life:"),
            view=ReviveSelectView(self.owner_id, dead),
            ephemeral=True,
        )


class Inventory(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="inventory", description="View your gold, tokens, shields, fragments, and items.")
    @register_user
    async def inventory(self, interaction: discord.Interaction) -> None:
        items = await queries.get_inventory(interaction.user.id)
        user = await queries.get_user(interaction.user.id)
        embed = inventory_embed(items)
        embed.add_field(name="Gold", value=f"{user.gold:,}", inline=True)

        primed_notes: list[str] = []
        if items.get("red_buff_primed", 0) > 0:
            primed_notes.append(
                f"🔴 Red Buff primed ×{items['red_buff_primed']} — fires on next fight."
            )
        if items.get("blue_buff_primed", 0) > 0:
            primed_notes.append(
                f"🔵 Blue Buff primed ×{items['blue_buff_primed']} — skips next action cooldown."
            )
        if primed_notes:
            embed.add_field(
                name="✨ Primed effects",
                value="\n".join(primed_notes),
                inline=False,
            )

        embed.set_footer(
            text="Shields auto-equip against incoming PvP. Use the buttons below to prime buffs."
        )

        view = InventoryView(interaction.user.id, items)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="shields", description="Quick view of your shield stockpile.")
    @register_user
    async def shields(self, interaction: discord.Interaction) -> None:
        items = await queries.get_inventory(interaction.user.id)
        lines = [
            f"Physical: **{items.get('shield_physical', 0)}**",
            f"Magic:    **{items.get('shield_magic', 0)}**",
            f"Aegis:    **{items.get('aegis', 0)}**",
            f"Stasis:   **{items.get('stasis', 0)}**",
            "",
            "_All shields auto-equip against incoming PvP — typed shields block matching damage first._",
        ]
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Shields", description="\n".join(lines), color=0x607D8B
            ),
            ephemeral=True,
        )

    @app_commands.command(name="profile", description="Your level, XP, prestige, gold, and unlocks.")
    @register_user
    async def profile(self, interaction: discord.Interaction) -> None:
        user = await queries.get_user(interaction.user.id)
        owned = await queries.list_owned(interaction.user.id)
        loadout = await queries.get_loadout(interaction.user.id)
        embed = profile_embed(user, champ_count=len(owned), loadout_size=len(loadout))
        embed.title = f"{interaction.user.display_name}'s profile"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # /champions removed in v2.x — use `/loadout → 📚 Collection` instead.


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Inventory(bot))
