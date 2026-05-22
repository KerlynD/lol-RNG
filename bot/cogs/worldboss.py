"""World boss cog — /strike, /worldboss, admin spawn helpers."""
from __future__ import annotations

import logging
import random
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.champions.leveling import HUNT_PASSIVE_SHARE, WORLDBOSS_STRIKE_XP
from bot.game.champions.xp import award_champ_xp
from bot.game.combat import power_score
from bot.game.pve.world_bosses import (
    CONFIG_BOSS_CHANNEL,
    WORLD_BOSSES,
    hp_scaled,
)
from bot.utils.decorators import register_user
from bot.utils.embeds import failure_embed, info_embed, world_boss_embed

log = logging.getLogger(__name__)

STRIKE_COOLDOWN = timedelta(minutes=5)


class WorldBossCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="worldboss", description="Show the active world boss + leaderboard.")
    @register_user
    async def worldboss(self, interaction: discord.Interaction) -> None:
        boss = await queries.get_active_world_boss()
        if boss is None:
            await interaction.response.send_message(
                embed=info_embed("No world boss is active. Watch the channel — one will appear in the coming days."),
                ephemeral=True,
            )
            return
        spec = WORLD_BOSSES.get(boss.boss_key)
        top = await queries.list_top_strikers(boss.id, limit=5)
        you_dealt = next(
            (dmg for uid, dmg in top if uid == interaction.user.id),
            0,
        )
        embed = world_boss_embed(boss, spec, top, you_dealt)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="strike", description="Strike the active world boss with your best champion.")
    @register_user
    async def strike(self, interaction: discord.Interaction) -> None:
        boss = await queries.get_active_world_boss()
        if boss is None:
            await interaction.response.send_message(
                embed=failure_embed("No world boss is active right now."),
                ephemeral=True,
            )
            return

        remaining = await queries.get_strike_cooldown(interaction.user.id, boss.id)
        if remaining is not None:
            await interaction.response.send_message(
                embed=failure_embed(f"You can strike again in {int(remaining // 60)}m {int(remaining % 60)}s."),
                ephemeral=True,
            )
            return

        loadout = await queries.alive_loadout(interaction.user.id)
        if not loadout:
            await interaction.response.send_message(
                embed=failure_embed("You have no alive champion. Check `/menu` for revive timers."),
                ephemeral=True,
            )
            return

        # Best alive champ leads the strike.
        lead = max((e.champion for e in loadout), key=power_score)
        user = await queries.get_user(interaction.user.id)
        rng = random.Random()
        base_damage = int(power_score(lead, user.level, user.prestige) * 5 * rng.uniform(0.9, 1.1))

        new_hp, defeated = await queries.apply_strike(boss.id, interaction.user.id, base_damage)
        if new_hp < 0:
            await interaction.response.send_message(
                embed=failure_embed("The boss is no longer active."), ephemeral=True
            )
            return

        await queries.set_strike_cooldown(interaction.user.id, boss.id, STRIKE_COOLDOWN)

        # World bosses are a top champ-XP source — every strike feeds the loadout.
        levelups = await award_champ_xp(
            interaction.user.id, loadout, lead.id,
            WORLDBOSS_STRIKE_XP, HUNT_PASSIVE_SHARE,
        )
        levelup_note = ""
        if levelups:
            names = ", ".join(lu.champion.name for lu in levelups)
            levelup_note = f"\n🆙 **{names}** levelled up — spend points with `/champion`."

        spec = WORLD_BOSSES.get(boss.boss_key)
        boss_name = spec.name if spec else boss.boss_key
        if defeated:
            await self._resolve_defeat(interaction, boss.id, spec, base_damage, lead)
        else:
            await interaction.response.send_message(
                embed=info_embed(
                    f"⚔ **{lead.name}** strikes {boss_name} for **{base_damage:,}** damage. "
                    f"HP remaining: **{new_hp:,} / {boss.hp_total:,}**.{levelup_note}"
                )
            )

    async def _resolve_defeat(
        self,
        interaction: discord.Interaction,
        boss_id: int,
        spec,
        last_damage: int,
        lead,
    ) -> None:
        top = await queries.list_top_strikers(boss_id, limit=10)
        # Distribute rewards
        if spec is None:
            await interaction.response.send_message(
                embed=info_embed(f"World boss defeated by {lead.name}'s killing blow!")
            )
            return

        for rank, (uid, dmg) in enumerate(top):
            try:
                if rank < 3:
                    await queries.add_gold(uid, spec.top_three_gold)
                    if spec.fragment_drop:
                        await queries.add_item(uid, spec.fragment_drop, 1)
                    if spec.extra_drop:
                        await queries.add_item(uid, spec.extra_drop, 1)
                else:
                    await queries.add_gold(uid, spec.participation_gold)
            except Exception:
                log.exception("Failed to distribute rewards to %s", uid)

        leaderboard = "\n".join(
            f"{i + 1}. <@{uid}> — {dmg:,} dmg"
            for i, (uid, dmg) in enumerate(top[:5])
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"🏆 {spec.name} defeated!",
                description=(
                    f"**{lead.name}** lands the killing blow ({last_damage:,} dmg).\n\n"
                    f"**Leaderboard**\n{leaderboard}\n\n"
                    f"Top 3 receive **{spec.top_three_gold:,} Gold** + "
                    f"{spec.fragment_drop or '—'}"
                    + (f" + {spec.extra_drop}" if spec.extra_drop else "")
                    + f"\nEveryone else who struck receives **{spec.participation_gold:,} Gold**."
                ),
                color=0xFFD700,
            )
        )

    # ----- Admin --------------------------------------------------------------

    @app_commands.command(
        name="admin-set-boss-channel",
        description="(Admin) Designate this channel as the world boss spawn announcement channel.",
    )
    @app_commands.default_permissions(administrator=True)
    @register_user
    async def admin_set_boss_channel(self, interaction: discord.Interaction) -> None:
        await queries.set_config(CONFIG_BOSS_CHANNEL, str(interaction.channel_id))
        await interaction.response.send_message(
            embed=info_embed(f"World bosses will now spawn in <#{interaction.channel_id}>."),
            ephemeral=True,
        )

    @app_commands.command(
        name="admin-spawn-boss",
        description="(Admin) Manually spawn a world boss (for testing).",
    )
    @app_commands.describe(boss_key="One of: rift_herald, baron, atakhan, elder_dragon")
    @app_commands.default_permissions(administrator=True)
    @register_user
    async def admin_spawn_boss(self, interaction: discord.Interaction, boss_key: str) -> None:
        spec = WORLD_BOSSES.get(boss_key)
        if spec is None:
            await interaction.response.send_message(
                embed=failure_embed(f"Unknown boss key: {boss_key}"),
                ephemeral=True,
            )
            return
        existing = await queries.get_active_world_boss()
        if existing:
            await interaction.response.send_message(
                embed=failure_embed("Another world boss is already active."),
                ephemeral=True,
            )
            return
        channel_id_str = await queries.get_config(CONFIG_BOSS_CHANNEL)
        channel_id = int(channel_id_str) if channel_id_str else interaction.channel_id
        active = await queries.active_users_last_7d()
        hp = hp_scaled(spec, active)
        boss = await queries.spawn_world_boss(spec.key, channel_id, hp, spec.window)
        channel = self.bot.get_channel(channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                embed=failure_embed("Configured boss channel is invalid."),
                ephemeral=True,
            )
            return
        await channel.send(
            content="@here",
            embed=discord.Embed(
                title=f"🐉 {spec.name} has appeared!",
                description=(
                    f"{spec.flavor}\n\n"
                    f"HP: **{hp:,}** · Window: **{int(spec.window.total_seconds() // 60)} min**\n"
                    f"Strike with `/strike`."
                ),
                color=0xFFD700,
            ),
        )
        await interaction.response.send_message(
            embed=info_embed(f"Spawned {spec.name} (HP {hp:,}, boss #{boss.id})."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorldBossCog(bot))
