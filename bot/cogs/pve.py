"""PVE cog — /hunt-camp engage/back-out flow + /explore + /lore."""
from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.combat import power_score
from bot.game.economy import gold_payout
from bot.game.leveling import apply_xp
from bot.game.pve.camps import CampSpec, cooldown_seconds, roll_encounter
from bot.game.pve.combat import (
    DEFAULT_RESPAWN_SEC,
    FAIL_GOLD_PCT,
    PVE_WIN_PCT_BY_DIFF,
    RESPAWN_DURATION_SEC,
    WEAKNESS_BONUS_PCT,
    lead_champion,
    preview_win_pct,
)
from bot.game.pve.encounters import (
    REGIONS,
    CombatEncounter,
    LoreEncounter,
    TreasureEncounter,
    pick_encounter,
    regions_list,
)
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

EXPLORE_COOLDOWN = timedelta(hours=3)

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

    # ── Regional exploration ─────────────────────────────────────────────

    @app_commands.command(
        name="explore",
        description="Travel to a region of Runeterra. Random encounter, 3h cooldown.",
    )
    @app_commands.describe(region="Which region to explore.")
    @app_commands.choices(
        region=[app_commands.Choice(name=r, value=r) for r in regions_list()]
    )
    @register_user
    async def explore(self, interaction: discord.Interaction, region: str) -> None:
        cd_key = f"explore:{region.lower()}"
        remaining = await queries.check_cooldown(interaction.user.id, cd_key)
        if remaining is not None:
            await interaction.response.send_message(
                embed=cooldown_embed(f"Explore {region}", remaining), ephemeral=True
            )
            return

        # Require a champ from that region in the alive loadout.
        loadout = await queries.alive_loadout(interaction.user.id)
        regional_champs = [e.champion for e in loadout if e.champion.region == region]
        if not regional_champs:
            await interaction.response.send_message(
                embed=failure_embed(
                    f"You need a **{region}** champion (alive) in your loadout to explore there."
                ),
                ephemeral=True,
            )
            return

        rng = random.Random()
        encounter = pick_encounter(region, rng=rng)
        await queries.set_cooldown(
            interaction.user.id, cd_key, EXPLORE_COOLDOWN
        )

        user = await queries.get_user(interaction.user.id)
        lead = max(regional_champs, key=power_score)

        if isinstance(encounter, CombatEncounter):
            await self._handle_combat(interaction, encounter, user, lead, region)
        elif isinstance(encounter, TreasureEncounter):
            await self._handle_treasure(interaction, encounter, user, region)
        elif isinstance(encounter, LoreEncounter):
            await self._handle_lore(interaction, encounter, user, region)

    async def _handle_combat(
        self,
        interaction: discord.Interaction,
        enc: "CombatEncounter",
        user,
        lead,
        region: str,
    ) -> None:
        mob = enc.mob
        diff = max(-4, min(4, lead.tier - mob.tier))
        win_pct = PVE_WIN_PCT_BY_DIFF[diff]
        if mob.weak_to and lead.damage_type == mob.weak_to:
            win_pct = min(99.0, win_pct + WEAKNESS_BONUS_PCT)
        rng = random.Random()
        won = rng.uniform(0, 100) < win_pct

        if won:
            gold_reward = gold_payout(mob.base_gold, user.level, user.prestige)
            xp_result = apply_xp(user.xp, user.level, mob.base_xp)
            await queries.add_gold(user.discord_id, gold_reward)
            await queries.set_user_level_xp(
                user.discord_id, xp_result.new_level, xp_result.new_xp
            )
            level_line = (
                f"\n:sparkles: **Level up → {xp_result.leveled_up_to}**"
                if xp_result.leveled_up_to
                else ""
            )
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"🗺 {region} — Victory",
                    description=(
                        f"{enc.flavor}\n\n"
                        f"**{lead.name}** dispatches the **{mob.name}**.\n"
                        f"Gold **+{gold_reward:,}** · XP **+{mob.base_xp}**{level_line}"
                    ),
                    color=0x4CAF50,
                )
            )
        else:
            respawn = RESPAWN_DURATION_SEC.get(diff, DEFAULT_RESPAWN_SEC)
            penalty = min(user.gold, int(mob.base_gold * FAIL_GOLD_PCT))
            await queries.add_gold(user.discord_id, -penalty)
            await queries.kill_champion(
                user.discord_id, lead.id, timedelta(seconds=respawn)
            )
            await interaction.response.send_message(
                embed=discord.Embed(
                    title=f"🗺 {region} — Defeated",
                    description=(
                        f"{enc.flavor}\n\n"
                        f"**{lead.name}** falls to the **{mob.name}**.\n"
                        f"Gold lost: **{penalty}** · {lead.name} dies for **{respawn // 60} min**."
                    ),
                    color=0xF44336,
                )
            )

    async def _handle_treasure(
        self,
        interaction: discord.Interaction,
        enc: "TreasureEncounter",
        user,
        region: str,
    ) -> None:
        rng = random.Random()
        gold = gold_payout(enc.base_gold, user.level, user.prestige)
        await queries.add_gold(user.discord_id, gold)
        drop_line = ""
        if enc.bonus_drop and rng.random() < enc.drop_chance:
            await queries.add_item(user.discord_id, enc.bonus_drop, 1)
            label = enc.bonus_drop.replace("_", " ").title()
            drop_line = f"\nBonus drop: **{label} ×1**"
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"🗺 {region} — Treasure",
                description=f"{enc.flavor}\n\nGold **+{gold:,}**{drop_line}",
                color=0xFFC107,
            )
        )

    async def _handle_lore(
        self,
        interaction: discord.Interaction,
        enc: "LoreEncounter",
        user,
        region: str,
    ) -> None:
        newly = await queries.unlock_lore(user.discord_id, enc.lore_key)
        title = (
            f"🗺 {region} — Lore unlocked"
            if newly
            else f"🗺 {region} — A familiar tale"
        )
        desc = f"{enc.flavor}\n\n{enc.lore_text}"
        if newly:
            desc += "\n\n_Saved to your `/lore` collection._"
        await interaction.response.send_message(
            embed=discord.Embed(title=title, description=desc, color=0x9C27B0)
        )

    @app_commands.command(name="lore", description="View the lore entries you've unlocked.")
    @register_user
    async def lore(self, interaction: discord.Interaction) -> None:
        entries = await queries.list_lore(interaction.user.id)
        if not entries:
            await interaction.response.send_message(
                embed=info_embed("You haven't unlocked any lore yet. Try `/explore`!"),
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
