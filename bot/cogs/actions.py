"""Actions cog — the solo PRD action commands, wired through the registry runner.

One command per action key. PvP-triggering actions (prank, duel, heist, raid)
are not commands here — they are buttons on the /attack panel (bot/cogs/pvp.py).
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


# Action keys for the action commands defined in this cog (no god/death; those are in a separate cog).
SOLO_ACTION_KEYS = (
    "work", "beg", "daily",                                        # T1
    "forage", "tinker",                                            # T2 solo
    "patrol-demacia", "meditate-ionia", "hunt-shadowisles",        # T3 solo
    "ascend", "darkin-pact", "defend-targon", "void-touch",        # T4
    "void-incursion", "celestial-gaze", "freljord-storm", "judgment",  # T5
)

# PvP-triggering actions (prank, duel, heist-piltover, raid-noxus) are no
# longer standalone commands — they are buttons on the /attack panel in
# bot/cogs/pvp.py. Their ActionSpecs still live in the registry.


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

    # ----- Solo (no @target) -------------------------------------------------

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

    @app_commands.command(name="forage", description=ACTIONS["forage"].description)
    @register_user
    async def forage(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "forage")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="tinker", description=ACTIONS["tinker"].description)
    @register_user
    async def tinker(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "tinker")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="patrol-demacia", description=ACTIONS["patrol-demacia"].description)
    @register_user
    async def patrol_demacia(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "patrol-demacia")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="meditate-ionia", description=ACTIONS["meditate-ionia"].description)
    @register_user
    async def meditate_ionia(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "meditate-ionia")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="hunt-shadowisles", description=ACTIONS["hunt-shadowisles"].description)
    @register_user
    async def hunt_shadowisles(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "hunt-shadowisles")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="ascend", description=ACTIONS["ascend"].description)
    @register_user
    async def ascend(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "ascend")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="darkin-pact", description=ACTIONS["darkin-pact"].description)
    @register_user
    async def darkin_pact(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "darkin-pact")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="defend-targon", description=ACTIONS["defend-targon"].description)
    @register_user
    async def defend_targon(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "defend-targon")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="void-touch", description=ACTIONS["void-touch"].description)
    @register_user
    async def void_touch(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "void-touch")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="void-incursion", description=ACTIONS["void-incursion"].description)
    @register_user
    async def void_incursion(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "void-incursion")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="celestial-gaze", description=ACTIONS["celestial-gaze"].description)
    @register_user
    async def celestial_gaze(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "celestial-gaze")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="freljord-storm", description=ACTIONS["freljord-storm"].description)
    @register_user
    async def freljord_storm(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "freljord-storm")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))

    @app_commands.command(name="judgment", description=ACTIONS["judgment"].description)
    @register_user
    async def judgment(self, interaction: discord.Interaction) -> None:
        result = await _run_and_reply(interaction, "judgment")
        if result is not None:
            await interaction.response.send_message(embed=action_result_embed(result))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Actions(bot))
