"""Menu cog — /menu personalized dashboard of what you can do right now."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.actions.registry import ACTIONS, ActionSpec
from bot.game.actions.runner import (
    COOLDOWN,
    ELIGIBLE,
    LEVEL_LOCKED,
    LOADOUT_LOCKED,
    check_eligibility,
)
from bot.game.economy import ROLL_COSTS
from bot.game.leveling import unlocks_for
from bot.game.pvp_flow import (
    LAMBS_RESPITE_COOLDOWN_KEY,
    PVP_ATTACKS_RECEIVED_CAP,
    WORLD_ENDER_COOLDOWN_KEY,
)
from bot.utils.decorators import register_user

log = logging.getLogger(__name__)


def _format_seconds(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"


def _format_action_with_champ(av) -> str:
    line = f"`{av.spec.name}`"
    if av.chosen_champ_name:
        line += f" — via {av.chosen_champ_name}"
    return line


def _affordable_rolls(gold: int, roll_tokens: int) -> list[str]:
    out: list[str] = []
    if roll_tokens > 0:
        out.append(f"`/roll` (1 Roll Token)")
    if gold >= ROLL_COSTS[1] and roll_tokens == 0:
        out.append(f"`/roll` ({ROLL_COSTS[1]:,}g)")
    for m in (10, 100, 1000):
        if gold >= ROLL_COSTS[m]:
            out.append(f"`/roll{m}` ({ROLL_COSTS[m]:,}g)")
    return out


class Menu(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="menu",
        description="What can you do right now? Personalized dashboard of actions, rolls, PvP, trades.",
    )
    @register_user
    async def menu(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        user_id = interaction.user.id
        user = await queries.get_user(user_id)
        loadout = await queries.alive_loadout(user_id)
        full_loadout = await queries.get_loadout(user_id)
        dead_champs = await queries.dead_champions_for_user(user_id)
        cooldowns = await queries.get_all_cooldowns(user_id)
        inventory = await queries.get_inventory(user_id)
        unlocks = unlocks_for(user.level)
        roll_tokens = inventory.get("roll_token", 0)

        # Bucket every action by eligibility status — only over ALIVE loadout.
        buckets: dict[str, list] = {
            ELIGIBLE: [],
            COOLDOWN: [],
            LOADOUT_LOCKED: [],
            LEVEL_LOCKED: [],
        }
        for spec in ACTIONS.values():
            av = check_eligibility(spec, user.level, loadout, cooldowns)
            buckets[av.status].append(av)

        # ── Header ─────────────────────────────────────────────────────────
        alive_count = len(loadout)
        equipped_count = len(full_loadout)
        loadout_label = f"{alive_count}/{equipped_count}" if equipped_count else "empty"
        if equipped_count and alive_count < equipped_count:
            loadout_label += " alive"
        header_lines = [
            f"**Level** {user.level} · **{user.gold:,} Gold** · **{roll_tokens} Roll Token(s)**",
            f"**Loadout** {loadout_label}/{unlocks.loadout_slots} · "
            f"**Action tiers unlocked** T1–T{unlocks.max_action_tier}",
        ]
        if user.prestige > 0:
            header_lines.append(f"**Prestige:** {user.prestige} (+{5 * user.prestige}% Gold)")

        embed = discord.Embed(
            title=f"What can {interaction.user.display_name} do?",
            description="\n".join(header_lines),
            color=0x3F51B5,
        )

        # ── PVE Hunt ────────────────────────────────────────────────────────
        hunt_cd = cooldowns.get("hunt-camp")
        hunt_lines: list[str] = []
        if hunt_cd is None:
            if loadout:
                hunt_lines.append("✅ **`/hunt-camp` ready** — wander into the jungle.")
            else:
                hunt_lines.append("✅ `/hunt-camp` ready — but you have no alive champion.")
        else:
            hunt_lines.append(f"⏳ Next hunt in **{_format_seconds(hunt_cd)}**.")
        # Active buffs / souls
        if inventory.get("red_buff", 0) > 0:
            hunt_lines.append(f"🔴 Red Buff ×{inventory['red_buff']} — next fight +10% win.")
        if inventory.get("blue_buff", 0) > 0:
            hunt_lines.append(f"🔵 Blue Buff ×{inventory['blue_buff']} — next action skips cooldown.")
        owned_souls = [
            k.replace("dragon_soul_", "").title()
            for k in inventory
            if k.startswith("dragon_soul_") and inventory[k] > 0
        ]
        if owned_souls:
            hunt_lines.append("🐉 Dragon Souls: " + ", ".join(sorted(owned_souls)))
        embed.add_field(name="🌲 PVE", value="\n".join(hunt_lines), inline=False)

        # ── Dead champions ──────────────────────────────────────────────────
        if dead_champs:
            dead_lines = [
                f"💀 **{name}** — revives in {_format_seconds(remaining)}"
                for _, name, remaining in dead_champs
            ]
            embed.add_field(
                name=f"💀 Dead ({len(dead_champs)})",
                value="\n".join(dead_lines)[:1024],
                inline=False,
            )

        # ── Available actions ──────────────────────────────────────────────
        if buckets[ELIGIBLE]:
            # Sort by tier so high-impact options surface first.
            buckets[ELIGIBLE].sort(key=lambda av: (-av.spec.tier, av.spec.name))
            lines = [_format_action_with_champ(av) for av in buckets[ELIGIBLE]]
            embed.add_field(
                name=f"✅ Available now ({len(lines)})",
                value="\n".join(lines)[:1024] or "—",
                inline=False,
            )
        else:
            embed.add_field(
                name="✅ Available now",
                value="_Nothing — wait for cooldowns or equip new champs._",
                inline=False,
            )

        # ── Rolls ──────────────────────────────────────────────────────────
        rolls = _affordable_rolls(user.gold, roll_tokens)
        if rolls:
            embed.add_field(
                name="🎲 Rolls you can afford",
                value=" · ".join(rolls),
                inline=False,
            )
        else:
            embed.add_field(
                name="🎲 Rolls",
                value="_Earn Gold via `/daily` or `/work` to roll._",
                inline=False,
            )

        # Fragment redemption hints
        fragment_hints = []
        for tier in range(1, 7):
            qty = inventory.get(f"fragment_t{tier}", 0)
            from bot.game.economy import FRAGMENT_THRESHOLDS
            need = FRAGMENT_THRESHOLDS[tier]
            if qty >= need:
                fragment_hints.append(f"`/redeem-fragment tier:{tier}` ({qty}/{need})")
        if fragment_hints:
            embed.add_field(
                name="🧩 Fragments ready",
                value="\n".join(fragment_hints),
                inline=False,
            )

        # ── On cooldown ────────────────────────────────────────────────────
        if buckets[COOLDOWN]:
            buckets[COOLDOWN].sort(key=lambda av: av.seconds_remaining or 0)
            lines = [
                f"`{av.spec.name}` — ready in {_format_seconds(av.seconds_remaining)}"
                for av in buckets[COOLDOWN][:8]
            ]
            extra = len(buckets[COOLDOWN]) - len(lines)
            if extra > 0:
                lines.append(f"_…and {extra} more_")
            embed.add_field(
                name=f"⏳ On cooldown ({len(buckets[COOLDOWN])})",
                value="\n".join(lines),
                inline=False,
            )

        # ── Loadout-locked ─────────────────────────────────────────────────
        if buckets[LOADOUT_LOCKED]:
            buckets[LOADOUT_LOCKED].sort(key=lambda av: (av.spec.tier, av.spec.name))
            lines = [
                f"`{av.spec.name}` — needs {av.missing_requirement}"
                for av in buckets[LOADOUT_LOCKED][:8]
            ]
            extra = len(buckets[LOADOUT_LOCKED]) - len(lines)
            if extra > 0:
                lines.append(f"_…and {extra} more_")
            embed.add_field(
                name=f"🔒 Bring a different champion ({len(buckets[LOADOUT_LOCKED])})",
                value="\n".join(lines),
                inline=False,
            )

        # ── Level-locked (grouped by tier, compact) ────────────────────────
        if buckets[LEVEL_LOCKED]:
            by_tier: dict[int, list[ActionSpec]] = {}
            min_levels: dict[int, int] = {}
            for av in buckets[LEVEL_LOCKED]:
                by_tier.setdefault(av.spec.tier, []).append(av.spec)
                min_levels[av.spec.tier] = av.required_level or 1
            tier_lines = []
            for tier in sorted(by_tier):
                names = ", ".join(s.name for s in by_tier[tier])
                tier_lines.append(f"**T{tier}** (need Lv{min_levels[tier]}): {names}")
            embed.add_field(
                name="🌑 Locked by level",
                value="\n".join(tier_lines),
                inline=False,
            )

        # ── PvP status ─────────────────────────────────────────────────────
        attacks_received = await queries.count_recent_attacks_received(user_id, hours=24)
        immune_remaining = cooldowns.get(LAMBS_RESPITE_COOLDOWN_KEY)
        world_ender_remaining = cooldowns.get(WORLD_ENDER_COOLDOWN_KEY)
        reap_mark = await queries.get_reap_mark(user_id)
        passive = inventory.get("kindred_passive", 0)

        pvp_lines = [
            f"Attacks received today: **{attacks_received} / {PVP_ATTACKS_RECEIVED_CAP}**",
            (
                f"Shields — Phys: {inventory.get('shield_physical', 0)} · "
                f"Magic: {inventory.get('shield_magic', 0)} · "
                f"Aegis: {inventory.get('aegis', 0)} · "
                f"Stasis: {inventory.get('stasis', 0)}"
            ),
        ]
        if len(loadout) > 0:
            pvp_lines.append("Use `/attack @user` to challenge a player (best-of-3 skirmish).")
        else:
            pvp_lines.append("_You need at least one equipped champion to attack._")
        embed.add_field(name="⚔ PvP status", value="\n".join(pvp_lines), inline=False)

        # ── Active effects (only if any) ───────────────────────────────────
        active = []
        if immune_remaining is not None:
            active.append(f"🌿 **Lamb's Respite** — PvP immune for {_format_seconds(immune_remaining)}")
        if world_ender_remaining is not None:
            active.append(f"🩸 **World Ender** — 2× PvP Gold for {_format_seconds(world_ender_remaining)}")
        if reap_mark is not None:
            caster_id, expires = reap_mark
            active.append(f"💀 **Reaped** by <@{caster_id}> — next unique pull diverts to them")
        if passive > 0:
            active.append(f"🏹 **Kindred's Passive** ready — next incoming PvP auto-ties")
        if active:
            embed.add_field(name="✨ Active effects", value="\n".join(active), inline=False)

        # ── Trades ─────────────────────────────────────────────────────────
        trades = await queries.list_pending_trades_for_user(user_id)
        if trades:
            embed.add_field(
                name=f"📦 Pending trades ({len(trades)})",
                value="Use `/trades` to view, `/accept <id>` or `/decline <id>`.",
                inline=False,
            )

        # ── Prestige nudge ─────────────────────────────────────────────────
        if unlocks.can_prestige:
            embed.add_field(
                name="🌟 Endgame",
                value="You're at Level 30 — `/prestige` for a permanent boost.",
                inline=False,
            )

        embed.set_footer(text="Tip: this menu is personal to you. Run /menu any time.")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menu(bot))
