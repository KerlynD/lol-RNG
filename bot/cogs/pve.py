"""PVE cog — /hunt-camp with engage/back-out flow."""
from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.pve.camps import CampSpec, cooldown_seconds, roll_encounter
from bot.game.pve.combat import lead_champion, preview_win_pct
from bot.game.pve.runner import (
    HUNT_CAMP_KEY,
    run_camp_back_out,
    run_camp_engage,
)
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    camp_result_embed,
    cooldown_embed,
    encounter_embed,
    failure_embed,
    info_embed,
)

if TYPE_CHECKING:
    from bot.db.queries import Champion

log = logging.getLogger(__name__)

ENCOUNTER_TIMEOUT_SEC = 60


class HuntEncounterView(discord.ui.View):
    """Two-button view: Hunt! / Back out. Auto-back-out after 60s."""

    def __init__(self, *, owner_id: int, camp: CampSpec, champ: "Champion | None"):
        super().__init__(timeout=float(ENCOUNTER_TIMEOUT_SEC))
        self.owner_id = owner_id
        self.camp = camp
        self.champ = champ
        self.message: discord.Message | None = None
        self.resolved = False

        if champ is None:
            # No alive champ — disable both buttons (we still create them for layout).
            for child in self.children:
                child.disabled = True  # type: ignore[attr-defined]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your encounter.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self.resolved or self.champ is None:
            return
        # Auto back-out
        try:
            user = await queries.get_user(self.owner_id)
            if user:
                cd = await run_camp_back_out(user, self.camp)
                if self.message:
                    await self.message.edit(
                        embed=info_embed(
                            f"⏱ You hesitated too long. {self.camp.name} fades into the brush. "
                            f"Hunt cooldown: {cd}s."
                        ),
                        view=None,
                    )
        except Exception:
            log.exception("auto-back-out failed")

    @discord.ui.button(label="Hunt!", style=discord.ButtonStyle.success, emoji="⚔")
    async def hunt(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if self.champ is None:
            await interaction.response.send_message(
                embed=failure_embed("All your champions are dead. Check `/menu`."),
                ephemeral=True,
            )
            return

        self.resolved = True
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]

        user = await queries.get_user(self.owner_id)
        outcome = await run_camp_engage(user, self.camp, self.champ)
        await interaction.response.edit_message(
            embed=camp_result_embed(self.camp, self.champ, outcome),
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Back out", style=discord.ButtonStyle.secondary, emoji="🏃")
    async def back_out(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.resolved = True
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]

        user = await queries.get_user(self.owner_id)
        cd = await run_camp_back_out(user, self.camp)
        await interaction.response.edit_message(
            embed=info_embed(
                f"🏃 You back away from {self.camp.name}. Hunt cooldown: {cd}s."
            ),
            view=self,
        )
        self.stop()


class PVE(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="hunt-camp",
        description="Wander into the jungle. You don't choose what you'll find.",
    )
    @register_user
    async def hunt_camp(self, interaction: discord.Interaction) -> None:
        # 1. Cooldown check
        remaining = await queries.check_cooldown(interaction.user.id, HUNT_CAMP_KEY)
        if remaining is not None:
            await interaction.response.send_message(
                embed=cooldown_embed("Hunt", remaining), ephemeral=True
            )
            return

        # 2. Roll the encounter
        rng = random.Random()
        camp = roll_encounter(rng=rng)

        # 3. Pick the best alive champion (if any)
        loadout = await queries.alive_loadout(interaction.user.id)
        champ = lead_champion(loadout)

        # 4. Compute preview and post the encounter
        if champ is None:
            embed = encounter_embed(camp, None, 0.0)
            embed.description = (
                f"{embed.description}\n\n"
                "**All your champions are dead.** Check `/menu` for revive timers. "
                "Backing out will still cost a cooldown."
            )
            view = HuntEncounterView(
                owner_id=interaction.user.id, camp=camp, champ=None
            )
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()
            return

        win_pct = preview_win_pct(champ, camp)
        embed = encounter_embed(camp, champ, win_pct)
        view = HuntEncounterView(
            owner_id=interaction.user.id, camp=camp, champ=champ
        )
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PVE(bot))
