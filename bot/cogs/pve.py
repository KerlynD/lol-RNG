"""PVE cog — /hunt-camp engage/back-out flow + /lore.

Region exploration is folded into the /adventure hub (Phase 5); see
bot/game/world/explore.py and bot/cogs/adventure.py.
"""
from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.pve.camps import CampSpec, cooldown_seconds
from bot.game.pve.combat import lead_champion, preview_win_pct
from bot.game.pve.encounters import REGIONS, LoreEncounter
from bot.game.pve.runner import (
    HUNT_CAMP_KEY,
    run_camp_engage,
)
from bot.game.world.monsters import (
    REGION_POOLS,
    roll_region_encounter,
    wild_champ_chance,
    wild_champion_camp,
)
from bot.game.world.regions import (
    MAX_CHAMPION_TIER,
    get_region,
    reward_decay_factor,
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
    """Two-button view: Hunt! / Back out. Auto-back-out after 60s.

    The hunt-camp cooldown is set at /hunt-camp invocation (not here) to block
    spam. This view's job is purely to resolve the encounter outcome.
    """

    def __init__(
        self,
        *,
        owner_id: int,
        camp: CampSpec,
        champ: Champion | None,
        cooldown_set: int,
        reward_factor: float = 1.0,
        opponent_splash: str | None = None,
        region_key: str = "",
    ):
        super().__init__(timeout=float(ENCOUNTER_TIMEOUT_SEC))
        self.owner_id = owner_id
        self.camp = camp
        self.champ = champ
        self.cooldown_set = cooldown_set
        self.reward_factor = reward_factor
        self.opponent_splash = opponent_splash
        self.region_key = region_key
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
        # Auto back-out — cooldown was set on /hunt-camp; nothing else to do.
        try:
            if self.message:
                await self.message.edit(
                    embed=info_embed(
                        f"⏱ You hesitated too long. {self.camp.name} fades into the brush."
                    ),
                    view=None,
                )
        except Exception:
            log.exception("auto-back-out edit failed")

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
        outcome = await run_camp_engage(
            user, self.camp, self.champ, reward_factor=self.reward_factor
        )
        # Region unlock-goal progress: count won hunts (and wild-champ kills).
        if outcome.fight.won and self.region_key:
            await queries.incr_goal_progress(
                self.owner_id, f"{self.region_key}:hunt_wins"
            )
            if self.camp.key.startswith("wild:"):
                await queries.incr_goal_progress(
                    self.owner_id, f"{self.region_key}:wild_kills"
                )
        await interaction.response.edit_message(
            embed=camp_result_embed(
                self.camp, self.champ, outcome,
                opponent_splash=self.opponent_splash,
            ),
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

        # Cooldown is already set; no DB call needed on back-out.
        await interaction.response.edit_message(
            embed=info_embed(
                f"🏃 You back away from {self.camp.name}. Hunt cooldown: {self.cooldown_set}s."
            ),
            view=self,
        )
        self.stop()


class PVE(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="hunt-camp",
        description="Hunt the monsters of the region you're standing in.",
    )
    @register_user
    async def hunt_camp(self, interaction: discord.Interaction) -> None:
        # 1. Cooldown check — blocks both spam-spawning AND post-resolve repeats.
        remaining = await queries.check_cooldown(interaction.user.id, HUNT_CAMP_KEY)
        if remaining is not None:
            await interaction.response.send_message(
                embed=cooldown_embed("Hunt", remaining), ephemeral=True
            )
            return

        user = await queries.get_user(interaction.user.id)
        region = get_region(user.current_region if user else None)
        if region is None or region.key not in REGION_POOLS:
            await interaction.response.send_message(
                embed=failure_embed(
                    "You have no region to hunt in — run `/start-adventure`."
                ),
                ephemeral=True,
            )
            return

        # 2. Roll the encounter — region monster, or a wild champion.
        rng = random.Random()
        opponent_splash: str | None = None
        camp: CampSpec | None = None
        if rng.random() < wild_champ_chance(region.key):
            cap = min(region.tier_max, MAX_CHAMPION_TIER)
            candidates = await queries.champions_in_regions(
                list(region.champ_regions), region.tier_min, cap
            )
            if candidates:
                weights = [region.tier_max - c.tier + 1 for c in candidates]
                wild = rng.choices(candidates, weights=weights, k=1)[0]
                camp = wild_champion_camp(wild)
                opponent_splash = wild.splash_url
        if camp is None:
            camp = roll_region_encounter(region.key, rng=rng)
        if camp is None:  # defensive — region always has a pool here
            await interaction.response.send_message(
                embed=failure_embed("The region is strangely quiet. Try again."),
                ephemeral=True,
            )
            return

        # 3. SET COOLDOWN IMMEDIATELY (before any further work) — anti-spam.
        cd = cooldown_seconds(camp, rng=rng)
        from bot.game.pve.souls import cooldown_factor
        cd = int(cd * await cooldown_factor(interaction.user.id))
        cd = max(cd, 5)
        await queries.set_cooldown(
            interaction.user.id, HUNT_CAMP_KEY, timedelta(seconds=cd)
        )

        # 4. Backtracking decay — hunting a region behind your frontier pays less.
        unlocked = await queries.list_unlocked_regions(interaction.user.id)
        reward_factor = reward_decay_factor(region.key, unlocked)

        # 5. Pick the best alive champion (if any)
        loadout = await queries.alive_loadout(interaction.user.id)
        champ = lead_champion(loadout)

        if champ is None:
            embed = encounter_embed(camp, None, 0.0, opponent_splash=opponent_splash)
            embed.description = (
                f"{embed.description}\n\n"
                "**All your champions are dead.** Check `/menu` for revive timers. "
                "The hunt cooldown still applies."
            )
            view = HuntEncounterView(
                owner_id=interaction.user.id, camp=camp, champ=None,
                cooldown_set=cd, reward_factor=reward_factor,
                opponent_splash=opponent_splash, region_key=region.key,
            )
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()
            return

        win_pct = preview_win_pct(champ, camp)
        embed = encounter_embed(camp, champ, win_pct, opponent_splash=opponent_splash)
        if reward_factor < 1.0:
            embed.set_footer(
                text=f"⬇ Backtracking — rewards here scaled to {int(reward_factor * 100)}%."
            )
        view = HuntEncounterView(
            owner_id=interaction.user.id, camp=camp, champ=champ,
            cooldown_set=cd, reward_factor=reward_factor,
            opponent_splash=opponent_splash, region_key=region.key,
        )
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()

    # ── Lore collection ──────────────────────────────────────────────────

    @app_commands.command(name="lore", description="View the lore entries you've unlocked.")
    @register_user
    async def lore(self, interaction: discord.Interaction) -> None:
        entries = await queries.list_lore(interaction.user.id)
        if not entries:
            await interaction.response.send_message(
                embed=info_embed(
                    "You haven't unlocked any lore yet. Explore via `/adventure`!"
                ),
                ephemeral=True,
            )
            return

        # Index lore_key -> (region, lore_text) by scanning REGIONS
        index: dict[str, tuple[str, str]] = {}
        for region, pool in REGIONS.items():
            for enc in pool:
                if isinstance(enc, LoreEncounter):
                    index[enc.lore_key] = (region, enc.lore_text)

        grouped: dict[str, list[str]] = {}
        for lore_key, _ in entries:
            if lore_key in index:
                region, text = index[lore_key]
                grouped.setdefault(region, []).append(text)

        embed = discord.Embed(
            title=f"📜 Lore unlocked ({len(entries)})",
            color=0x9C27B0,
        )
        for region in sorted(grouped):
            embed.add_field(
                name=region,
                value="\n\n".join(grouped[region])[:1024],
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PVE(bot))
