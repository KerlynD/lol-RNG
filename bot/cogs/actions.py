"""Actions cog — the global economy commands.

v3 folded the region/faction solo actions (forage, tinker, patrol-demacia,
ascend, …) into the /adventure → Region Actions panel, and the PvP-triggering
raids (prank, duel, heist, raid) into the /attack panel (bot/cogs/pvp.py).
What remains here is the global economy floor — /work, /beg, /daily — which
needs no region and no @target. All still flow through run_action.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.actions.registry import ACTIONS
from bot.game.actions.runner import ActionFailure, ActionSuccess, run_action
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    action_result_embed,
    cooldown_embed,
    failure_embed,
)

log = logging.getLogger(__name__)


async def _run_and_reply(interaction: discord.Interaction, key: str) -> ActionSuccess | None:
    user = await queries.get_user(interaction.user.id)
    result = await run_action(user, key)
    if isinstance(result, ActionFailure):
        spec = ACTIONS[key]
        if result.seconds_remaining is not None:
            embed = cooldown_embed(spec.name, result.seconds_remaining)
        else:
            embed = failure_embed(result.reason)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return None
    return result


class Actions(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="work", description=ACTIONS["work"].description)
    @register_user
    async def work(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "work")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="beg", description=ACTIONS["beg"].description)
    @register_user
    async def beg(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "beg")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="daily", description=ACTIONS["daily"].description)
    @register_user
    async def daily(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "daily")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Actions(bot))
