"""Adventure cog — /start-adventure (the way into the game) and /adventure.

v3 makes Runeterra a place: every player has a location, and the rest of the
bot is gated behind /start-adventure (see bot/utils/gating.py). /adventure is
the hub command — it shows your location, region unlock goals, and a Travel
selector. Quests and folded Region Actions arrive in later phases.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.world.goals import all_goals_met, evaluate_goals
from bot.game.world.regions import (
    STARTING_REGION,
    WORLD,
    get_region,
    travel_cooldown_minutes,
    travel_cost,
)
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    adventure_hub_embed,
    adventure_welcome_embed,
    failure_embed,
    info_embed,
    region_arrival_embed,
    travel_embed,
)

log = logging.getLogger(__name__)

TRAVEL_CD_KEY = "_travel"
HUB_TIMEOUT_SEC = 180


async def _neighbor_goal_map(user, unlocked: list[str]) -> dict:
    """Locked-neighbour region_key -> list[GoalStatus], for the hub embed."""
    region = get_region(user.current_region)
    if region is None:
        return {}
    unlocked_set = set(unlocked)
    progress = await queries.all_goal_progress(user.discord_id)
    out: dict = {}
    for nb_key in region.neighbors:
        if nb_key in unlocked_set:
            continue
        out[nb_key] = evaluate_goals(nb_key, user.gold, user.level, progress)
    return out


async def _destination_options(user, unlocked: list[str]) -> list[tuple[str, str, str]]:
    """Regions the player can travel to right now: (key, label, description)."""
    region = get_region(user.current_region)
    if region is None:
        return []
    unlocked_set = set(unlocked)
    progress = await queries.all_goal_progress(user.discord_id)
    out: list[tuple[str, str, str]] = []
    for nb_key in region.neighbors:
        nb = WORLD.get(nb_key)
        if nb is None:
            continue
        cost = travel_cost(region.key, nb_key)
        if nb_key in unlocked_set:
            out.append((nb_key, f"Travel to {nb.display}", f"{cost:,} Gold"))
        elif all_goals_met(nb_key, user.gold, user.level, progress):
            out.append((
                nb_key,
                f"Unlock & travel to {nb.display}",
                f"{cost:,} Gold · goals complete!",
            ))
    return out


async def _do_travel(interaction: discord.Interaction, dest_key: str) -> None:
    uid = interaction.user.id
    user = await queries.get_user(uid)
    region = get_region(user.current_region if user else None)
    if region is None or dest_key not in region.neighbors:
        await interaction.response.edit_message(
            embed=failure_embed("You can't reach there from here."), view=None
        )
        return

    cd = await queries.check_cooldown(uid, TRAVEL_CD_KEY)
    if cd is not None:
        await interaction.response.edit_message(
            embed=failure_embed(
                f"You're still resting from your last journey ({int(cd // 60)}m "
                f"{int(cd % 60)}s). Travel again soon."
            ),
            view=None,
        )
        return

    unlocked = await queries.list_unlocked_regions(uid)
    is_locked = dest_key not in unlocked
    if is_locked:
        progress = await queries.all_goal_progress(uid)
        if not all_goals_met(dest_key, user.gold, user.level, progress):
            await interaction.response.edit_message(
                embed=failure_embed(
                    f"You haven't completed **{WORLD[dest_key].display}**'s "
                    "unlock goals yet. Check `/adventure`."
                ),
                view=None,
            )
            return

    cost = travel_cost(region.key, dest_key)
    if user.gold < cost:
        await interaction.response.edit_message(
            embed=failure_embed(
                f"The journey to **{WORLD[dest_key].display}** costs **{cost:,}** "
                f"Gold — you have {user.gold:,}."
            ),
            view=None,
        )
        return

    if cost:
        await queries.add_gold(uid, -cost)
    await queries.set_current_region(uid, dest_key)
    cd_min = travel_cooldown_minutes(region.key, dest_key)
    await queries.set_cooldown(uid, TRAVEL_CD_KEY, timedelta(minutes=cd_min))

    if is_locked:
        await queries.unlock_region(uid, dest_key)
        log.info("User %s unlocked region %s", uid, dest_key)
        await interaction.response.edit_message(
            embed=info_embed(
                f"You travel onward and unlock **{WORLD[dest_key].display}**!"
            ),
            view=None,
        )
        # Public story beat — the server sees a new land conquered.
        await interaction.followup.send(
            content=f"🌟 {interaction.user.mention} has reached a new region!",
            embed=region_arrival_embed(dest_key),
        )
    else:
        await interaction.response.edit_message(
            embed=travel_embed(dest_key, cost), view=None
        )


class AdventureHubView(discord.ui.View):
    """The /adventure dashboard view — currently a Travel selector."""

    def __init__(self, owner_id: int, destinations: list[tuple[str, str, str]]):
        super().__init__(timeout=float(HUB_TIMEOUT_SEC))
        self.owner_id = owner_id
        if destinations:
            self.add_item(_TravelSelect(destinations))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "This isn't your adventure.", ephemeral=True
            )
            return False
        return True


class _TravelSelect(discord.ui.Select):
    def __init__(self, destinations: list[tuple[str, str, str]]):
        options = [
            discord.SelectOption(label=label[:100], value=key, description=desc[:100])
            for key, label, desc in destinations[:25]
        ]
        super().__init__(placeholder="🗺 Travel to…", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await _do_travel(interaction, self.values[0])


class Adventure(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="start-adventure",
        description="Begin your journey through Runeterra. Start here!",
    )
    @register_user
    async def start_adventure(self, interaction: discord.Interaction) -> None:
        user = await queries.get_user(interaction.user.id)
        if user is not None and user.adventure_started_at is not None:
            unlocked = await queries.list_unlocked_regions(interaction.user.id)
            goals = await _neighbor_goal_map(user, unlocked)
            await interaction.response.send_message(
                embeds=[
                    info_embed("Your adventure is already underway:"),
                    adventure_hub_embed(user, unlocked, goals),
                ],
                ephemeral=True,
            )
            return

        await queries.start_adventure(interaction.user.id, STARTING_REGION)
        log.info("User %s started their adventure.", interaction.user.id)
        await interaction.response.send_message(embed=adventure_welcome_embed())

    @app_commands.command(
        name="adventure",
        description="Your adventure hub — where you are in Runeterra and what's next.",
    )
    @register_user
    async def adventure(self, interaction: discord.Interaction) -> None:
        user = await queries.get_user(interaction.user.id)
        unlocked = await queries.list_unlocked_regions(interaction.user.id)
        goals = await _neighbor_goal_map(user, unlocked)
        travel_cd = await queries.check_cooldown(interaction.user.id, TRAVEL_CD_KEY)
        destinations = (
            [] if travel_cd else await _destination_options(user, unlocked)
        )
        await interaction.response.send_message(
            embed=adventure_hub_embed(user, unlocked, goals, travel_cd),
            view=AdventureHubView(interaction.user.id, destinations),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Adventure(bot))
