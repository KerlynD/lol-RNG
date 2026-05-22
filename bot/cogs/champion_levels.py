"""Champion levels cog — the ability-upgrade popup + /champion panel.

The level-up popup is spawned by /hunt-camp (bot/cogs/pve.py) as a
non-ephemeral follow-up. /champion lets players spend banked ability points
on champions that levelled up passively.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.db.queries import Champion, ChampProgress
from bot.game.champions.abilities import can_rank
from bot.utils.decorators import register_user
from bot.utils.embeds import champion_ability_embed, failure_embed, info_embed

log = logging.getLogger(__name__)

_SLOT_EMOJI = {"q": "🇶", "w": "🇼", "e": "🇪", "r": "🇷"}
_SLOT_CAP = {"q": 5, "w": 5, "e": 5, "r": 3}


class AbilityUpgradeView(discord.ui.View):
    """Q/W/E/R upgrade buttons for one champion. Used by the level-up popup
    and by /champion. Banked points persist regardless of this view's life."""

    def __init__(
        self,
        owner_id: int,
        champion: Champion,
        progress: ChampProgress,
        *,
        leveled_to: int | None = None,
    ):
        super().__init__(timeout=300.0)
        self.owner_id = owner_id
        self.champion = champion
        self.progress = progress
        self.leveled_to = leveled_to
        self._sync()

    def embed(self) -> discord.Embed:
        return champion_ability_embed(
            self.champion, self.progress, leveled_to=self.leveled_to
        )

    def _sync(self) -> None:
        for slot, button in (
            ("q", self.upgrade_q), ("w", self.upgrade_w),
            ("e", self.upgrade_e), ("r", self.upgrade_r),
        ):
            rank = getattr(self.progress, f"{slot}_rank")
            button.label = f"{slot.upper()}  {rank}/{_SLOT_CAP[slot]}"
            button.disabled = not can_rank(slot, self.progress)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your champion.", ephemeral=True
            )
            return False
        return True

    async def _rank(self, interaction: discord.Interaction, slot: str) -> None:
        updated = await queries.rank_ability(self.owner_id, self.champion.id, slot)
        if updated is None:
            # Lost a race (no points / capped) — re-sync from the DB.
            updated = await queries.get_champ_progress(self.owner_id, self.champion.id)
        if updated is not None:
            self.progress = updated
        self.leveled_to = None  # after the first click it's just a panel
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Q", style=discord.ButtonStyle.success, emoji="🇶")
    async def upgrade_q(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._rank(interaction, "q")

    @discord.ui.button(label="W", style=discord.ButtonStyle.success, emoji="🇼")
    async def upgrade_w(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._rank(interaction, "w")

    @discord.ui.button(label="E", style=discord.ButtonStyle.success, emoji="🇪")
    async def upgrade_e(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._rank(interaction, "e")

    @discord.ui.button(label="R", style=discord.ButtonStyle.danger, emoji="🇷")
    async def upgrade_r(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._rank(interaction, "r")


class _ChampionSelect(discord.ui.Select):
    def __init__(self, owner_id: int, owned: list):
        self.owner_id = owner_id
        # champion_id -> (Champion, ChampProgress)
        self._index = {str(o.champion.id): (o.champion, o.progress) for o in owned}
        options = [
            discord.SelectOption(
                label=o.champion.name[:100],
                value=str(o.champion.id),
                description=(
                    f"Champ Lv {o.progress.champ_level} · "
                    f"{o.progress.unspent_points} point(s) unspent"
                )[:100],
            )
            for o in owned
        ]
        super().__init__(
            placeholder="Pick a champion…", options=options, min_values=1, max_values=1
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        champion, progress = self._index[self.values[0]]
        view = AbilityUpgradeView(self.owner_id, champion, progress)
        await interaction.response.edit_message(embed=view.embed(), view=view)


class ChampionPickerView(discord.ui.View):
    def __init__(self, owner_id: int, owned: list):
        super().__init__(timeout=180.0)
        self.owner_id = owner_id
        self.add_item(_ChampionSelect(owner_id, owned))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your champion menu.", ephemeral=True
            )
            return False
        return True


class ChampionLevels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="champion",
        description="View a champion's level and spend its ability points.",
    )
    @register_user
    async def champion(self, interaction: discord.Interaction) -> None:
        owned = await queries.list_owned(interaction.user.id)
        if not owned:
            await interaction.response.send_message(
                embed=failure_embed("You don't own any champions yet — try `/roll`."),
                ephemeral=True,
            )
            return
        # Champions with unspent points float to the top.
        owned.sort(
            key=lambda o: (
                o.progress.unspent_points,
                o.progress.champ_level,
                o.champion.tier,
            ),
            reverse=True,
        )
        shown = owned[:25]
        note = "" if len(owned) <= 25 else f"\n_Showing 25 of {len(owned)} champions._"
        await interaction.response.send_message(
            embed=info_embed(
                "Pick a champion to view its level and spend ability points."
                + note
            ),
            view=ChampionPickerView(interaction.user.id, shown),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChampionLevels(bot))
