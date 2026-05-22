"""PvP cog — the /attack control panel, /rank, /leaderboard, /spy.

/attack opens an ephemeral panel whose buttons cover every way to attack a
player: a ranked best-of-3 skirmish, an unranked single-round duel, a prank,
and the region-locked Heist / Raid actions. The old standalone /duel, /prank,
/heist-piltover and /raid-noxus slash commands have been folded into it.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.actions.registry import ACTIONS
from bot.game.actions.runner import (
    COOLDOWN,
    ELIGIBLE,
    LEVEL_LOCKED,
    LOADOUT_LOCKED,
    ActionAvailability,
    ActionFailure,
    check_eligibility,
    run_action,
)
from bot.game.pvp_flow import attempt_pvp, check_pvp_eligibility
from bot.game.ranked_flow import attempt_ranked_match
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    TIER_NAME,
    action_result_embed,
    attack_panel_embed,
    cooldown_embed,
    failure_embed,
    leaderboard_embed,
    rank_card_embed,
    ranked_result_embeds,
    skirmish_embeds,
)

log = logging.getLogger(__name__)


def _fmt_secs(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h {(s % 3600) // 60}m"


def _availability_note(a: ActionAvailability) -> str:
    """Why a panel button is disabled, in a few words."""
    if a.status == COOLDOWN:
        return f"on cooldown ({_fmt_secs(a.seconds_remaining or 0)})"
    if a.status == LEVEL_LOCKED:
        return f"unlocks at level {a.required_level}"
    if a.status == LOADOUT_LOCKED:
        return f"needs a {a.missing_requirement} champion equipped"
    return "unavailable"


def _eligibility_message(status: str, target_name: str, fallback: str) -> str:
    if status == "immune":
        return f"{target_name} is wreathed in Lamb's Respite. Untouchable."
    if status == "capped":
        return f"{target_name} is rested — no more attacks today."
    if status == "no_defender":
        return f"{target_name} has no alive champion equipped."
    if status == "no_attacker":
        return "You have no alive champion equipped — check /menu for revive timers."
    return fallback


# ----------------------------------------------------------------------------
# Shared button handlers
# ----------------------------------------------------------------------------


async def _run_pvp_action(
    interaction: discord.Interaction,
    key: str,
    target: discord.Member,
    *,
    stake_pct: float,
    best_of: int,
) -> None:
    """Gold-PvP panel buttons (Unranked Duel / Prank / Heist / Raid).

    Mirrors the old actions._pvp_action flow: precheck the target, run the
    action for its Gold/XP/cooldown, then resolve the skirmish."""
    await interaction.response.defer()
    attacker_id = interaction.user.id

    reason, status = await check_pvp_eligibility(attacker_id, target.id)
    if reason is not None:
        await interaction.followup.send(
            embed=failure_embed(_eligibility_message(status, target.display_name, reason)),
            ephemeral=True,
        )
        return

    user = await queries.get_user(attacker_id)
    result = await run_action(user, key)
    if isinstance(result, ActionFailure):
        spec = ACTIONS[key]
        if result.seconds_remaining is not None:
            embed = cooldown_embed(spec.name, result.seconds_remaining)
        else:
            embed = failure_embed(result.reason)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return

    await interaction.followup.send(embed=action_result_embed(result))

    outcome = await attempt_pvp(
        attacker_id, target.id, gold_stake_pct=stake_pct, best_of=best_of
    )
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
                f"{target.display_name}'s Kindred passive triggers — "
                "neither of you wins this exchange."
            )
        )
        return

    await interaction.followup.send(
        embeds=skirmish_embeds(
            interaction.user, target, outcome.skirmish, outcome.gold_transferred
        )
    )


async def _run_ranked(interaction: discord.Interaction, target: discord.Member) -> None:
    """The Ranked Match panel button — a best-of-3 skirmish that moves LP."""
    await interaction.response.defer()
    outcome = await attempt_ranked_match(interaction.user.id, target.id)

    if outcome.immune:
        await interaction.followup.send(
            embed=failure_embed(
                f"{target.display_name} is wreathed in Lamb's Respite. Untouchable."
            )
        )
        return
    if outcome.error:
        desc = outcome.error
        if outcome.cooldown_seconds is not None:
            desc += f"\n\nTry again in **{_fmt_secs(outcome.cooldown_seconds)}**."
        await interaction.followup.send(embed=failure_embed(desc), ephemeral=True)
        return

    await interaction.followup.send(
        embeds=ranked_result_embeds(interaction.user, target, outcome)
    )


# ----------------------------------------------------------------------------
# Attack panel View
# ----------------------------------------------------------------------------


class AttackPanelView(discord.ui.View):
    def __init__(
        self,
        attacker_id: int,
        target: discord.Member,
        heist_ok: bool,
        raid_ok: bool,
    ):
        super().__init__(timeout=180.0)
        self.attacker_id = attacker_id
        self.target = target
        self.heist_btn.disabled = not heist_ok
        self.raid_btn.disabled = not raid_ok

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.attacker_id:
            await interaction.response.send_message(
                "This isn't your attack panel.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Ranked Match", style=discord.ButtonStyle.primary, emoji="⚔️")
    async def ranked_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await _run_ranked(interaction, self.target)

    @discord.ui.button(label="Unranked Duel", style=discord.ButtonStyle.secondary, emoji="🗡️")
    async def duel_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await _run_pvp_action(interaction, "duel", self.target, stake_pct=0.05, best_of=1)

    @discord.ui.button(label="Prank", style=discord.ButtonStyle.secondary, emoji="🃏")
    async def prank_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await _run_pvp_action(interaction, "prank", self.target, stake_pct=0.03, best_of=3)

    @discord.ui.button(label="Heist", style=discord.ButtonStyle.secondary, emoji="💰")
    async def heist_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await _run_pvp_action(
            interaction, "heist-piltover", self.target, stake_pct=0.12, best_of=3
        )

    @discord.ui.button(label="Raid", style=discord.ButtonStyle.secondary, emoji="🔥")
    async def raid_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await _run_pvp_action(
            interaction, "raid-noxus", self.target, stake_pct=0.15, best_of=3
        )


# ----------------------------------------------------------------------------
# Cog
# ----------------------------------------------------------------------------


class PvP(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="attack",
        description="Open the attack panel against another player.",
    )
    @app_commands.describe(target="Who to attack.")
    @register_user
    async def attack(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if target.bot:
            await interaction.response.send_message(
                embed=failure_embed("You can't attack a bot."), ephemeral=True
            )
            return
        if target.id == interaction.user.id:
            await interaction.response.send_message(
                embed=failure_embed("You can't attack yourself."), ephemeral=True
            )
            return

        attacker_id = interaction.user.id
        user = await queries.get_user(attacker_id)
        loadout = await queries.alive_loadout(attacker_id)
        cooldowns = await queries.get_all_cooldowns(attacker_id)

        heist = check_eligibility(ACTIONS["heist-piltover"], user.level, loadout, cooldowns)
        raid = check_eligibility(ACTIONS["raid-noxus"], user.level, loadout, cooldowns)
        heist_ok = heist.status == ELIGIBLE
        raid_ok = raid.status == ELIGIBLE

        embed = attack_panel_embed(
            interaction.user.display_name,
            target.display_name,
            loadout,
            heist_note="" if heist_ok else _availability_note(heist),
            raid_note="" if raid_ok else _availability_note(raid),
        )
        view = AttackPanelView(attacker_id, target, heist_ok, raid_ok)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="rank", description="View your ranked profile (or another player's).")
    @app_commands.describe(target="Whose rank to view. Defaults to you.")
    @register_user
    async def rank(
        self,
        interaction: discord.Interaction,
        target: discord.Member | None = None,
    ) -> None:
        member = target or interaction.user
        if member.bot:
            await interaction.response.send_message(
                embed=failure_embed("Bots don't have a rank."), ephemeral=True
            )
            return
        await queries.ensure_user(member.id)
        profile = await queries.ensure_ranked_profile(member.id)
        await interaction.response.send_message(
            embed=rank_card_embed(member.display_name, profile), ephemeral=True
        )

    @app_commands.command(name="leaderboard", description="The ranked LP leaderboard.")
    @register_user
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        profiles = await queries.top_ranked_profiles(limit=10)
        rows: list[tuple[int, str, queries.RankedProfile]] = []
        for i, p in enumerate(profiles, start=1):
            member = interaction.guild.get_member(p.user_id) if interaction.guild else None
            display = f"**{member.display_name}**" if member else f"<@{p.user_id}>"
            rows.append((i, display, p))
        await interaction.response.send_message(embed=leaderboard_embed(rows))

    @app_commands.command(
        name="spy",
        description="View a player you're hunting (granted by /eternal-hunt).",
    )
    @app_commands.describe(target="The player you've marked.")
    @register_user
    async def spy(self, interaction: discord.Interaction, target: discord.Member) -> None:
        # /eternal-hunt sets a cooldown row with action_key f'_hunt:{target_id}' as a 7-day "grant"
        key = f"_hunt:{target.id}"
        remaining = await queries.check_cooldown(interaction.user.id, key)
        if remaining is None:
            await interaction.response.send_message(
                embed=failure_embed(
                    f"You aren't hunting {target.display_name}. Cast `/eternal-hunt` first."
                ),
                ephemeral=True,
            )
            return

        t_user = await queries.get_user(target.id)
        if t_user is None:
            await interaction.response.send_message(
                embed=failure_embed("Target has no profile."), ephemeral=True
            )
            return
        t_load = await queries.get_loadout(target.id)
        t_inv = await queries.get_inventory(target.id)

        loadout_str = "\n".join(
            f"  Slot {e.slot}: {e.champion.name} ({TIER_NAME[e.champion.tier]}, {e.champion.damage_type})"
            for e in t_load
        ) or "  _empty_"
        shields_str = (
            f"  Physical: {t_inv.get('shield_physical', 0)}\n"
            f"  Magic:    {t_inv.get('shield_magic', 0)}\n"
            f"  Aegis:    {t_inv.get('aegis', 0)}\n"
            f"  Stasis:   {t_inv.get('stasis', 0)}"
        )
        desc = (
            f"Watching **{target.display_name}** (expires <t:{int((discord.utils.utcnow().timestamp() + remaining))}:R>)\n\n"
            f"**Level:** {t_user.level}    **Gold:** {t_user.gold:,}\n\n"
            f"**Loadout:**\n{loadout_str}\n\n"
            f"**Shields:**\n{shields_str}"
        )
        await interaction.response.send_message(
            embed=discord.Embed(title="Eternal Hunt", description=desc, color=0x000000),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PvP(bot))
