from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries

log = logging.getLogger(__name__)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check bot latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong — {latency_ms} ms.", ephemeral=True)

    # Epic tier — the v3 cutover wipes this tier and above.
    V3_WIPE_TIER = 4

    @app_commands.command(
        name="reset-v3",
        description="ADMIN: one-time v3 cutover — wipe Epic+ champions, reset all to Level 1.",
    )
    @app_commands.describe(confirm="Set to True to actually run the wipe.")
    async def reset_v3(self, interaction: discord.Interaction, confirm: bool = False) -> None:
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is None or not perms.administrator:
            await interaction.response.send_message(
                "This command is for server administrators only.", ephemeral=True
            )
            return

        if not confirm:
            await interaction.response.send_message(
                "⚠️ **v3 cutover — this affects EVERY player and cannot be undone.**\n"
                "• Removes all owned **Epic / Legendary / God / Death** champions "
                "(Tier 4+), unequipping them everywhere.\n"
                "• Resets everyone to **Level 1 / 0 XP**.\n"
                "• **Gold and prestige are kept.**\n\n"
                "Re-run with `confirm: True` to proceed.",
                ephemeral=True,
            )
            return

        try:
            result = await queries.admin_v3_reset(self.V3_WIPE_TIER)
        except Exception as e:
            log.exception("reset-v3 failed")
            await interaction.response.send_message(f"Reset error: {e}", ephemeral=True)
            return

        log.info("v3 reset run by %s: %s", interaction.user.id, result)
        await interaction.response.send_message(
            "✅ **v3 cutover complete.**\n"
            f"• Champions removed (Tier 4+): **{result['champions']}**\n"
            f"• Loadout slots cleared: **{result['loadout_slots']}**\n"
            f"• Players reset to Level 1: **{result['users_releveled']}**\n\n"
            "Everyone should now run `/start-adventure` and begin from Bandle City.",
            ephemeral=True,
        )

    @app_commands.command(
        name="spawns",
        description="Toggle automatic ambushes & world bosses on/off (admin only).",
    )
    @app_commands.describe(
        enabled="True to allow spawns, False to pause them (e.g. while you sleep)."
    )
    async def spawns(self, interaction: discord.Interaction, enabled: bool) -> None:
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is None or not perms.administrator:
            await interaction.response.send_message(
                "This command is for server administrators only.", ephemeral=True
            )
            return

        await queries.set_config("spawns_paused", "0" if enabled else "1")
        if enabled:
            msg = "🟢 Automatic ambient events & world bosses are now **ON**."
        else:
            msg = (
                "🔴 Automatic ambient events & world bosses are now **paused**. "
                "Nothing new will spawn until you run `/spawns enabled: True`. Sleep well. 😴"
            )
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="dbcheck", description="Verify DB connectivity and champion seed.")
    async def dbcheck(self, interaction: discord.Interaction) -> None:
        try:
            count = await queries.champion_count()
        except Exception as e:
            log.exception("dbcheck failed")
            await interaction.response.send_message(f"DB error: {e}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"DB OK. Champions seeded: **{count}**.", ephemeral=True
        )

    @app_commands.command(
        name="season-reset",
        description="End the ranked season — wipes all LP and restarts placements (admin only).",
    )
    @app_commands.describe(confirm="Set to True to confirm. This is irreversible.")
    async def season_reset(
        self, interaction: discord.Interaction, confirm: bool = False
    ) -> None:
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is None or not perms.administrator:
            await interaction.response.send_message(
                "You need the **Administrator** permission to reset the season.",
                ephemeral=True,
            )
            return
        if not confirm:
            await interaction.response.send_message(
                "This ends the current ranked season, wipes **every** player's LP, "
                "and forces a new round of placements. Re-run with `confirm: True` "
                "to proceed.",
                ephemeral=True,
            )
            return
        new_id = await queries.reset_season()
        await interaction.response.send_message(
            f"🏁 Ranked season reset — **Season {new_id}** has begun. "
            "All players must replay their placement matches."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
