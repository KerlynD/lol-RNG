"""Adventure gate — blocks game commands until a player runs /start-adventure.

Installed as a custom `CommandTree` on the bot. Every slash command passes
through `interaction_check`; commands are blocked unless the player has begun
their adventure. Two escape hatches:

- `/start-adventure` itself is always allowed (it's the way in).
- Server administrators bypass the gate entirely (covers the admin cog).
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands

from bot.db import queries
from bot.utils.embeds import failure_embed

log = logging.getLogger(__name__)

# Command names that work before the adventure has begun.
ALWAYS_ALLOWED: frozenset[str] = frozenset({"start-adventure"})


class AdventureGatedTree(app_commands.CommandTree):
    """A CommandTree that gates every command behind /start-adventure."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        command = interaction.command
        if command is None:
            return True

        root = command.qualified_name.split(" ")[0]
        if root in ALWAYS_ALLOWED:
            return True

        # Admins bypass — keeps /admin tooling usable before/around onboarding.
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is not None and perms.administrator:
            return True

        user = await queries.get_user(interaction.user.id)
        if user is not None and user.adventure_started_at is not None:
            return True

        await interaction.response.send_message(
            embed=failure_embed(
                "🌍 **Your adventure hasn't begun.**\n\n"
                "Runeterra is waiting. Run **/start-adventure** to step into the "
                "world from Bandle City — that unlocks rolling, hunting, and "
                "everything else."
            ),
            ephemeral=True,
        )
        return False

    async def on_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        # A blocked command raises CheckFailure — the gate already messaged the
        # user, so swallow it quietly. Everything else uses default handling.
        if isinstance(error, app_commands.CheckFailure):
            return
        await super().on_error(interaction, error)
