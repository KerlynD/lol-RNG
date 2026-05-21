"""Loadout cog — /loadout, /equip, /unequip, /lock, /unlock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.leveling import unlocks_for
from bot.utils.decorators import register_user
from bot.utils.embeds import failure_embed, info_embed, loadout_embed

LOADOUT_SWAP_COOLDOWN = timedelta(minutes=30)


async def _autocomplete_owned(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    owned = await queries.list_owned(interaction.user.id)
    needle = (current or "").lower()
    matches = [oc.champion.name for oc in owned if needle in oc.champion.name.lower()]
    return [app_commands.Choice(name=n, value=n) for n in matches[:25]]


def _swap_cooldown_remaining(last_swap: datetime | None) -> float:
    if last_swap is None:
        return 0.0
    now = datetime.now(tz=timezone.utc)
    elapsed = (now - last_swap).total_seconds()
    cd = LOADOUT_SWAP_COOLDOWN.total_seconds()
    return max(0.0, cd - elapsed)


class Loadout(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="loadout", description="Show your equipped champions.")
    @register_user
    async def loadout(self, interaction: discord.Interaction) -> None:
        user = await queries.get_user(interaction.user.id)
        entries = await queries.get_loadout(interaction.user.id)
        cap = unlocks_for(user.level).loadout_slots
        await interaction.response.send_message(embed=loadout_embed(entries, cap), ephemeral=True)

    @app_commands.command(name="equip", description="Equip a champion to a loadout slot.")
    @app_commands.describe(champion="Name of a champion you own.", slot="Slot number (1+).")
    @app_commands.autocomplete(champion=_autocomplete_owned)
    @register_user
    async def equip(
        self, interaction: discord.Interaction, champion: str, slot: int
    ) -> None:
        user = await queries.get_user(interaction.user.id)
        cap = unlocks_for(user.level).loadout_slots
        if slot < 1 or slot > cap:
            await interaction.response.send_message(
                embed=failure_embed(f"You only have {cap} loadout slot(s) at Level {user.level}."),
                ephemeral=True,
            )
            return

        champ = await queries.get_champion_by_name(champion)
        if champ is None:
            await interaction.response.send_message(
                embed=failure_embed(f"No champion named **{champion}** exists."),
                ephemeral=True,
            )
            return

        if not await queries.owns_champion(interaction.user.id, champ.id):
            await interaction.response.send_message(
                embed=failure_embed(f"You don't own **{champ.name}**."),
                ephemeral=True,
            )
            return

        # Already in some slot?
        current = await queries.get_loadout(interaction.user.id)
        for entry in current:
            if entry.champion.id == champ.id and entry.slot == slot:
                await interaction.response.send_message(
                    embed=info_embed(f"**{champ.name}** is already in slot {slot}."),
                    ephemeral=True,
                )
                return
            if entry.champion.id == champ.id and entry.slot != slot:
                await interaction.response.send_message(
                    embed=failure_embed(
                        f"**{champ.name}** is already equipped in slot {entry.slot}. Unequip first."
                    ),
                    ephemeral=True,
                )
                return

        # Swap cooldown applies if we're displacing an existing slot's champion.
        existing_in_slot = [e for e in current if e.slot == slot]
        if existing_in_slot:
            remaining = _swap_cooldown_remaining(user.last_loadout_swap)
            if remaining > 0:
                await interaction.response.send_message(
                    embed=failure_embed(
                        f"Loadout swap is on cooldown — try again in **{int(remaining // 60)}m {int(remaining % 60)}s**."
                    ),
                    ephemeral=True,
                )
                return

        await queries.set_loadout_slot(interaction.user.id, slot, champ.id)
        if existing_in_slot:
            await queries.stamp_loadout_swap(interaction.user.id)

        await interaction.response.send_message(
            embed=info_embed(f"Equipped **{champ.name}** to slot {slot}."),
            ephemeral=True,
        )

    @app_commands.command(name="unequip", description="Empty a loadout slot.")
    @app_commands.describe(slot="Slot number.")
    @register_user
    async def unequip(self, interaction: discord.Interaction, slot: int) -> None:
        user = await queries.get_user(interaction.user.id)
        remaining = _swap_cooldown_remaining(user.last_loadout_swap)
        if remaining > 0:
            await interaction.response.send_message(
                embed=failure_embed(
                    f"Loadout swap is on cooldown — try again in **{int(remaining // 60)}m {int(remaining % 60)}s**."
                ),
                ephemeral=True,
            )
            return
        cleared = await queries.clear_loadout_slot(interaction.user.id, slot)
        if not cleared:
            await interaction.response.send_message(
                embed=info_embed(f"Slot {slot} was already empty."),
                ephemeral=True,
            )
            return
        await queries.stamp_loadout_swap(interaction.user.id)
        await interaction.response.send_message(
            embed=info_embed(f"Slot {slot} cleared."),
            ephemeral=True,
        )

    @app_commands.command(name="lock", description="Lock a champion — protected from trade, sacrifice, and steal.")
    @app_commands.autocomplete(champion=_autocomplete_owned)
    @register_user
    async def lock(self, interaction: discord.Interaction, champion: str) -> None:
        champ = await queries.get_champion_by_name(champion)
        if champ is None or not await queries.owns_champion(interaction.user.id, champ.id):
            await interaction.response.send_message(
                embed=failure_embed(f"You don't own **{champion}**."),
                ephemeral=True,
            )
            return
        await queries.set_locked(interaction.user.id, champ.id, True)
        await interaction.response.send_message(
            embed=info_embed(f"🔒 **{champ.name}** locked."),
            ephemeral=True,
        )

    @app_commands.command(name="unlock", description="Unlock a champion.")
    @app_commands.autocomplete(champion=_autocomplete_owned)
    @register_user
    async def unlock(self, interaction: discord.Interaction, champion: str) -> None:
        champ = await queries.get_champion_by_name(champion)
        if champ is None or not await queries.owns_champion(interaction.user.id, champ.id):
            await interaction.response.send_message(
                embed=failure_embed(f"You don't own **{champion}**."),
                ephemeral=True,
            )
            return
        await queries.set_locked(interaction.user.id, champ.id, False)
        await interaction.response.send_message(
            embed=info_embed(f"🔓 **{champ.name}** unlocked."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Loadout(bot))
