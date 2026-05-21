"""Actions cog — every PRD action command, wired through the registry runner.

Single command per action key; PvP-triggering actions also resolve a skirmish
via bot.game.pvp_flow.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.actions.registry import ACTIONS, ActionSpec
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


# Action keys for the action commands defined in this cog (no god/death; those are in a separate cog).
SOLO_ACTION_KEYS = (
    "work", "beg", "daily",                                        # T1
    "forage", "tinker",                                            # T2 solo
    "patrol-demacia", "meditate-ionia", "hunt-shadowisles",        # T3 solo
    "ascend", "darkin-pact", "defend-targon", "void-touch",        # T4
    "void-incursion", "celestial-gaze", "freljord-storm", "judgment",  # T5
)

PVP_ACTION_KEYS = (
    "prank", "duel",            # T2
    "heist-piltover", "raid-noxus",  # T3
)


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

    # ----- PvP-triggering actions (require @target) --------------------------

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
            # Tailor messages for the most common cases for nicer copy.
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

        # Resolve PvP layer. Things can still go sideways (kindred_passive
        # auto-tie, or the target became immune between the precheck and now),
        # but those are rare and the user already saw the action result.
        outcome = await attempt_pvp(interaction.user.id, target.id, gold_stake_pct=stake_pct)
        if outcome.error:
            await interaction.followup.send(embed=failure_embed(outcome.error))
            return
        if outcome.immune or outcome.capped:
            # Edge: defender's state changed between precheck and execution.
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
