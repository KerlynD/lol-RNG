"""Actions cog — the global economy commands + PvP-triggering region raids.

v3 folded the region/faction solo actions (forage, tinker, patrol-demacia,
ascend, …) into the /adventure → Region Actions panel to cut command bloat.
What remains here:

- Global economy floor: /work, /beg, /daily (no region requirement).
- PvP-triggering region raids: /prank, /duel, /heist-piltover, /raid-noxus —
  these need an @target, so they stay slash commands rather than buttons.

All still flow through bot/game/actions/runner.run_action.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.actions.registry import ACTIONS
from bot.game.actions.runner import ActionFailure, ActionSuccess, run_action
from bot.game.pvp_flow import attempt_pvp, check_pvp_eligibility
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    action_result_embed,
    cooldown_embed,
    failure_embed,
    skirmish_embeds,
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

    # ----- Global economy (no region / no champ required) --------------------

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

    # ----- PvP-triggering region raids (require @target) ---------------------

    @app_commands.command(name="prank", description=ACTIONS["prank"].description)
    @app_commands.describe(target="Who to prank.")
    @register_user
    async def prank(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self._pvp_action(interaction, "prank", target, stake_pct=0.03)

    @app_commands.command(name="duel", description=ACTIONS["duel"].description)
    @app_commands.describe(target="Who to duel.")
    @register_user
    async def duel(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self._pvp_action(interaction, "duel", target, stake_pct=0.05)

    @app_commands.command(name="heist-piltover", description=ACTIONS["heist-piltover"].description)
    @app_commands.describe(target="Heist target.")
    @register_user
    async def heist_piltover(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self._pvp_action(interaction, "heist-piltover", target, stake_pct=0.12)

    @app_commands.command(name="raid-noxus", description=ACTIONS["raid-noxus"].description)
    @app_commands.describe(target="Raid target.")
    @register_user
    async def raid_noxus(self, interaction: discord.Interaction, target: discord.Member) -> None:
        await self._pvp_action(interaction, "raid-noxus", target, stake_pct=0.15)

    async def _pvp_action(
        self,
        interaction: discord.Interaction,
        key: str,
        target: discord.Member,
        stake_pct: float,
    ) -> None:
        if target.bot:
            await interaction.response.send_message(
                embed=failure_embed("You can't target a bot."), ephemeral=True
            )
            return

        # PRE-CHECK PvP target FIRST — if the target is immune/rested/no-champ,
        # we abort the WHOLE command. The action doesn't fire, no Gold/XP gets
        # paid, no cooldown is set. Single failure embed, no double-message.
        reason, _status = await check_pvp_eligibility(interaction.user.id, target.id)
        if reason is not None:
            if _status == "immune":
                msg = f"{target.display_name} is wreathed in Lamb's Respite. Untouchable."
            elif _status == "capped":
                msg = f"{target.display_name} is rested — no more attacks today."
            elif _status == "no_defender":
                msg = f"{target.display_name} has no alive champion equipped."
            elif _status == "no_attacker":
                msg = "You have no alive champion equipped — check `/menu` for revive timers."
            else:
                msg = reason
            await interaction.response.send_message(
                embed=failure_embed(msg), ephemeral=True
            )
            return

        # Eligibility confirmed — run the action.
        user = await queries.get_user(interaction.user.id)
        action_result = await run_action(user, key)
        if isinstance(action_result, ActionFailure):
            spec = ACTIONS[key]
            if action_result.seconds_remaining is not None:
                embed = cooldown_embed(spec.name, action_result.seconds_remaining)
            else:
                embed = failure_embed(action_result.reason)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.send_message(embed=action_result_embed(action_result))

        # Resolve PvP layer.
        outcome = await attempt_pvp(interaction.user.id, target.id, gold_stake_pct=stake_pct)
        if outcome.error:
            await interaction.followup.send(embed=failure_embed(outcome.error))
            return
        if outcome.immune or outcome.capped:
            await interaction.followup.send(
                embed=failure_embed(
                    f"{target.display_name} slipped away before the strike landed."
                )
            )
            return
        if outcome.auto_tied:
            await interaction.followup.send(
                embed=failure_embed(
                    f"{target.display_name}'s Kindred passive triggers — neither of you wins this exchange."
                )
            )
            return

        await interaction.followup.send(
            embeds=skirmish_embeds(
                interaction.user, target, outcome.skirmish, outcome.gold_transferred
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Actions(bot))
