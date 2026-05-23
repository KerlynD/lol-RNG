"""Adventure cog — /start-adventure (the way into the game) and /adventure.

v3 makes Runeterra a place: every player has a location, and the rest of the
bot is gated behind /start-adventure (see bot/utils/gating.py). /adventure is
the hub command — location, region unlock goals, a Travel selector, and a
Quests panel. Folded Region Actions arrive in Phase 5.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.db.pool import get_pool
from bot.game.actions.registry import ACTIONS
from bot.game.actions.runner import (
    ELIGIBLE,
    ActionFailure,
    check_eligibility,
    run_action,
)
from bot.game.leveling import apply_xp
from bot.game.world.explore import EXPLORE_COOLDOWN, run_explore
from bot.game.world.goals import all_goals_met, evaluate_goals
from bot.game.world.quests import quest_current, quests_for_region
from bot.game.world.void_hints import pick_hint, void_proximity
from bot.game.world.regions import (
    STARTING_REGION,
    WORLD,
    get_region,
    travel_cooldown_minutes,
    travel_cost,
)
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    action_result_embed,
    adventure_hub_embed,
    adventure_welcome_embed,
    cooldown_embed,
    failure_embed,
    info_embed,
    quest_complete_embed,
    quest_panel_embed,
    region_actions_embed,
    region_arrival_embed,
    travel_embed,
)

log = logging.getLogger(__name__)

TRAVEL_CD_KEY = "_travel"
HUB_TIMEOUT_SEC = 180

# Region/faction solo actions folded out of slash commands into /adventure.
REGION_ACTION_KEYS: dict[str, tuple[str, ...]] = {
    "bandle_city": ("forage",),
    "demacia": ("patrol-demacia",),
    "freljord": ("freljord-storm",),
    "ionia": ("meditate-ionia",),
    "piltover_zaun": ("tinker",),
    "shadow_isles": ("hunt-shadowisles",),
    "shurima": ("ascend", "darkin-pact"),
    "targon": ("defend-targon", "celestial-gaze", "judgment"),
    "void": ("void-touch", "void-incursion"),
}
# PvP raids surfaced in the hub but kept as slash commands (they need @target).
REGION_PVP_ACTIONS: dict[str, tuple[str, ...]] = {
    "piltover_zaun": ("heist-piltover",),
    "noxus": ("raid-noxus",),
}


def _region_has_actions(region_key: str) -> bool:
    return bool(
        REGION_ACTION_KEYS.get(region_key) or REGION_PVP_ACTIONS.get(region_key)
    )


# ── Goal / destination helpers ───────────────────────────────────────────────


async def _neighbor_goal_map(
    user, unlocked: list[str], progress: dict[str, int] | None = None
) -> dict:
    region = get_region(user.current_region)
    if region is None:
        return {}
    unlocked_set = set(unlocked)
    if progress is None:
        progress = await queries.all_goal_progress(user.discord_id)
    out: dict = {}
    for nb_key in region.neighbors:
        if nb_key in unlocked_set:
            continue
        out[nb_key] = evaluate_goals(nb_key, user.gold, user.level, progress)
    return out


async def _destination_options(
    user, unlocked: list[str], progress: dict[str, int] | None = None
) -> list[tuple[str, str, str]]:
    region = get_region(user.current_region)
    if region is None:
        return []
    unlocked_set = set(unlocked)
    if progress is None:
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


async def _quest_states(uid: int, user) -> list[tuple]:
    """(quest, status, current, target) for every quest in the user's region."""
    quests = quests_for_region(user.current_region or "")
    if not quests:
        return []
    user_quests = await queries.list_user_quests(uid)
    progress = await queries.all_goal_progress(uid)
    states: list[tuple] = []
    for quest in quests:
        status = user_quests.get(quest.key, "available")
        counter_key = quest.counter_key()
        current = quest_current(
            quest,
            counter_value=progress.get(counter_key, 0) if counter_key else 0,
            baseline=progress.get(f"_qbase:{quest.key}", 0),
            user_level=user.level,
            user_gold=user.gold,
        )
        states.append((quest, status, current, quest.objective_target))
    return states


async def _hub_view_and_embed(uid: int):
    user = await queries.get_user(uid)
    unlocked = await queries.list_unlocked_regions(uid)
    # One progress fetch — reused by goals, destinations, and the Void hint.
    progress = await queries.all_goal_progress(uid)
    goals = await _neighbor_goal_map(user, unlocked, progress=progress)
    travel_cd = await queries.check_cooldown(uid, TRAVEL_CD_KEY)
    has_quests = bool(quests_for_region(user.current_region or ""))
    has_actions = _region_has_actions(user.current_region or "")
    destinations = (
        [] if travel_cd
        else await _destination_options(user, unlocked, progress=progress)
    )
    void_hint = None
    if user.current_region in ("shurima", "targon"):
        proximity = void_proximity(
            user.gold, user.level, progress.get("shurima:hunt_wins", 0)
        )
        void_hint = pick_hint(user.current_region, proximity)
    embed = adventure_hub_embed(
        user, unlocked, goals, travel_cd, void_hint=void_hint
    )
    return embed, AdventureHubView(uid, destinations, has_quests, has_actions)


# ── Travel ───────────────────────────────────────────────────────────────────


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
                f"You're still resting from your last journey "
                f"({int(cd // 60)}m {int(cd % 60)}s)."
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
                    "unlock goals yet."
                ),
                view=None,
            )
            return

    cost = travel_cost(region.key, dest_key)
    if user.gold < cost:
        await interaction.response.edit_message(
            embed=failure_embed(
                f"The journey to **{WORLD[dest_key].display}** costs "
                f"**{cost:,}** Gold — you have {user.gold:,}."
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
        await interaction.followup.send(
            content=f"🌟 {interaction.user.mention} has reached a new region!",
            embed=region_arrival_embed(dest_key),
        )
    else:
        await interaction.response.edit_message(
            embed=travel_embed(dest_key, cost), view=None
        )


# ── Quests ───────────────────────────────────────────────────────────────────


async def _render_quest_panel(interaction: discord.Interaction, uid: int) -> None:
    user = await queries.get_user(uid)
    states = await _quest_states(uid, user)
    await interaction.response.edit_message(
        embed=quest_panel_embed(user.current_region or "", states),
        view=QuestPanelView(uid, states),
    )


async def _accept_quest(interaction: discord.Interaction, uid: int, quest) -> None:
    progress = await queries.all_goal_progress(uid)
    counter_key = quest.counter_key()
    baseline_key = f"_qbase:{quest.key}" if counter_key else None
    baseline_value = progress.get(counter_key, 0) if counter_key else 0
    await queries.accept_quest(uid, quest.key, baseline_key, baseline_value)
    await _render_quest_panel(interaction, uid)


async def _claim_quest(interaction: discord.Interaction, uid: int, quest) -> None:
    user = await queries.get_user(uid)
    states = await _quest_states(uid, user)
    match = next((s for s in states if s[0].key == quest.key), None)
    if match is None or match[1] != "active" or match[2] < match[3]:
        await _render_quest_panel(interaction, uid)
        return
    if not await queries.complete_quest(uid, quest.key):
        await _render_quest_panel(interaction, uid)
        return

    xp_result = apply_xp(user.xp, user.level, quest.reward_xp)
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if quest.reward_gold:
                await queries.add_gold(uid, quest.reward_gold, conn=conn)
            await queries.set_user_level_xp(
                uid, xp_result.new_level, xp_result.new_xp, conn=conn
            )
            if quest.reward_item and quest.reward_item_qty:
                await queries.add_item(
                    uid, quest.reward_item, quest.reward_item_qty, conn=conn
                )
    log.info("User %s completed quest %s", uid, quest.key)
    await interaction.response.edit_message(
        embed=quest_complete_embed(quest), view=None
    )
    await interaction.followup.send(
        content=f"📜 {interaction.user.mention} completed **{quest.title}**!",
        embed=quest_complete_embed(quest),
    )


# ── Explore + Region Actions ─────────────────────────────────────────────────


async def _do_explore(interaction: discord.Interaction) -> None:
    uid = interaction.user.id
    user = await queries.get_user(uid)
    region = get_region(user.current_region)
    if region is None:
        await interaction.response.edit_message(
            embed=failure_embed("You have no region to explore."), view=None
        )
        return
    cd_key = f"explore:{region.key}"
    cd = await queries.check_cooldown(uid, cd_key)
    if cd is not None:
        await interaction.response.edit_message(
            embed=cooldown_embed(f"Explore {region.display}", cd),
            view=_BackToHubView(uid),
        )
        return
    await queries.set_cooldown(uid, cd_key, EXPLORE_COOLDOWN)
    result = await run_explore(user, region.key)
    embed = discord.Embed(
        title=f"🔭 {result.title}",
        description=result.description,
        color=result.color,
    )
    await interaction.response.edit_message(embed=embed, view=_BackToHubView(uid))


async def _render_action_panel(interaction: discord.Interaction, uid: int) -> None:
    user = await queries.get_user(uid)
    region_key = user.current_region or ""
    loadout = await queries.alive_loadout(uid)
    cooldowns = await queries.get_all_cooldowns(uid)
    solo = REGION_ACTION_KEYS.get(region_key, ())
    pvp = REGION_PVP_ACTIONS.get(region_key, ())
    avails = [
        check_eligibility(ACTIONS[k], user.level, loadout, cooldowns) for k in solo
    ]
    await interaction.response.edit_message(
        embed=region_actions_embed(region_key, avails, list(pvp)),
        view=RegionActionView(uid, avails),
    )


async def _run_region_action(
    interaction: discord.Interaction, uid: int, action_key: str
) -> None:
    user = await queries.get_user(uid)
    result = await run_action(user, action_key)
    if isinstance(result, ActionFailure):
        if result.seconds_remaining is not None:
            embed = cooldown_embed(ACTIONS[action_key].name, result.seconds_remaining)
        else:
            embed = failure_embed(result.reason)
    else:
        embed = action_result_embed(result)
    await interaction.response.edit_message(embed=embed, view=_BackToHubView(uid))


# ── Views ────────────────────────────────────────────────────────────────────


class _OwnedView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=float(HUB_TIMEOUT_SEC))
        self.owner_id = owner_id

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
        super().__init__(
            placeholder="🗺 Travel to…", options=options, min_values=1, max_values=1
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _do_travel(interaction, self.values[0])


class _BackToHubView(_OwnedView):
    @discord.ui.button(label="Back to Adventure", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        embed, view = await _hub_view_and_embed(self.owner_id)
        await interaction.response.edit_message(embed=embed, view=view)


class AdventureHubView(_OwnedView):
    def __init__(
        self,
        owner_id: int,
        destinations: list[tuple[str, str, str]],
        has_quests: bool,
        has_actions: bool,
    ):
        super().__init__(owner_id)
        if destinations:
            self.add_item(_TravelSelect(destinations))
        if not has_quests:
            self.quests_button.disabled = True
        if not has_actions:
            self.actions_button.disabled = True

    @discord.ui.button(label="Quests", emoji="📜", style=discord.ButtonStyle.primary)
    async def quests_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await _render_quest_panel(interaction, self.owner_id)

    @discord.ui.button(label="Explore", emoji="🔭", style=discord.ButtonStyle.primary)
    async def explore_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await _do_explore(interaction)

    @discord.ui.button(label="Region Actions", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def actions_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await _render_action_panel(interaction, self.owner_id)


class _QuestButton(discord.ui.Button):
    def __init__(self, quest, status: str, current: int, target: int):
        self.quest = quest
        if status == "available":
            label, style, action, disabled = (
                f"Accept: {quest.title}", discord.ButtonStyle.success, "accept", False
            )
        elif status == "active" and current >= target:
            label, style, action, disabled = (
                f"Claim: {quest.title}", discord.ButtonStyle.success, "claim", False
            )
        elif status == "active":
            label, style, action, disabled = (
                f"{quest.title} — in progress", discord.ButtonStyle.secondary, "none", True
            )
        else:
            label, style, action, disabled = (
                f"{quest.title} — completed", discord.ButtonStyle.secondary, "none", True
            )
        self.action = action
        super().__init__(label=label[:80], style=style, disabled=disabled)

    async def callback(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        if self.action == "accept":
            await _accept_quest(interaction, uid, self.quest)
        elif self.action == "claim":
            await _claim_quest(interaction, uid, self.quest)


class QuestPanelView(_OwnedView):
    def __init__(self, owner_id: int, quest_states: list[tuple]):
        super().__init__(owner_id)
        for quest, status, current, target in quest_states:
            self.add_item(_QuestButton(quest, status, current, target))

    @discord.ui.button(label="Back", emoji="⬅️", style=discord.ButtonStyle.secondary, row=4)
    async def back_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        embed, view = await _hub_view_and_embed(self.owner_id)
        await interaction.response.edit_message(embed=embed, view=view)


class _ActionButton(discord.ui.Button):
    def __init__(self, avail):
        self.action_key = avail.spec.key
        eligible = avail.status == ELIGIBLE
        super().__init__(
            label=avail.spec.name[:80],
            style=discord.ButtonStyle.success if eligible else discord.ButtonStyle.secondary,
            disabled=not eligible,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await _run_region_action(interaction, interaction.user.id, self.action_key)


class RegionActionView(_OwnedView):
    def __init__(self, owner_id: int, avails: list):
        super().__init__(owner_id)
        for avail in avails:
            self.add_item(_ActionButton(avail))

    @discord.ui.button(label="Back", emoji="⬅️", style=discord.ButtonStyle.secondary, row=4)
    async def back_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        embed, view = await _hub_view_and_embed(self.owner_id)
        await interaction.response.edit_message(embed=embed, view=view)


# ── Cog ──────────────────────────────────────────────────────────────────────


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
        embed, view = await _hub_view_and_embed(interaction.user.id)
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Adventure(bot))
