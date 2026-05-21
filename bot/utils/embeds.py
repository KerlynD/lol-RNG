"""Discord embed builders shared across cogs."""
from __future__ import annotations

import discord

from bot.db.queries import Champion, LoadoutEntry, Trade, User
from bot.game.combat import SkirmishResult
from bot.game.actions.runner import ActionSuccess
from bot.game.leveling import unlocks_for, xp_to_next_level

TIER_COLOR: dict[int, int] = {
    1: 0x9E9E9E,
    2: 0x4CAF50,
    3: 0x2196F3,
    4: 0x9C27B0,
    5: 0xFFC107,
    6: 0xFF5722,
    7: 0x000000,
}

TIER_NAME: dict[int, str] = {
    1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic",
    5: "Legendary", 6: "God-Tier", 7: "Death",
}

ITEM_LABELS: dict[str, str] = {
    "roll_token": "Roll Token",
    "shield_physical": "Physical Shield",
    "shield_magic": "Magic Shield",
    "aegis": "Aegis",
    "stasis": "Stasis",
    "mat": "Mat",
    "soul": "Soul",
    "corruption_stack": "Corruption Stack",
    "kindred_passive": "Kindred's Passive",
    "red_buff": "Red Buff",
    "blue_buff": "Blue Buff",
    "dragon_soul_cloud": "Cloud Dragon Soul",
    "dragon_soul_ocean": "Ocean Dragon Soul",
    "dragon_soul_mountain": "Mountain Dragon Soul",
    "dragon_soul_infernal": "Infernal Dragon Soul",
    "dragon_soul_chemtech": "Chemtech Dragon Soul",
    "dragon_soul_hextech": "Hextech Dragon Soul",
    "dragon_soul_elder": "Elder Dragon Soul",
    **{f"fragment_t{t}": f"{TIER_NAME[t]} Fragment" for t in range(1, 7)},
}


def tier_embed(title: str, description: str, tier: int) -> discord.Embed:
    return discord.Embed(
        title=title, description=description, color=TIER_COLOR.get(tier, 0xCCCCCC)
    )


def pull_embed(champion: Champion, was_dupe: bool, fragment_qty: int | None) -> discord.Embed:
    tier_name = TIER_NAME[champion.tier]
    if was_dupe:
        desc = (
            f"**{champion.name}** ({tier_name})\n\n"
            f"You already own this champion. Converted to **{ITEM_LABELS[f'fragment_t{champion.tier}']}**.\n"
            f"You now hold {fragment_qty} {tier_name} fragment(s)."
        )
        title = "Duplicate pull"
    else:
        desc = (
            f"**{champion.name}** — {tier_name}\n"
            f"Region: {champion.region or '—'}\n"
            f"Damage Type: {champion.damage_type}\n"
        )
        title = "New champion!"
    embed = discord.Embed(title=title, description=desc, color=TIER_COLOR[champion.tier])
    if champion.splash_url:
        embed.set_thumbnail(url=champion.splash_url)
    return embed


def action_result_embed(success: ActionSuccess) -> discord.Embed:
    spec = success.spec
    lines = [f"**{spec.name}** — {spec.description}"]
    if success.gold_awarded:
        lines.append(f"Gold: **+{success.gold_awarded}**")
    if success.xp_awarded:
        lines.append(f"XP: **+{success.xp_awarded}**")
    if success.drops:
        drop_text = ", ".join(
            f"{ITEM_LABELS.get(t, t)} ×{q}" for t, q in success.drops
        )
        lines.append(f"Drops: **{drop_text}**")
    if success.synergy_bonus_applied:
        lines.append("_Synergy bonus applied._")
    if success.leveled_up_to:
        lines.append(f":sparkles: **Level Up! → {success.leveled_up_to}** :sparkles:")
    return discord.Embed(
        title="Action complete",
        description="\n".join(lines),
        color=TIER_COLOR[spec.tier],
    )


def cooldown_embed(action_name: str, seconds_remaining: float) -> discord.Embed:
    return discord.Embed(
        title="On cooldown",
        description=f"{action_name} is unavailable for **{_format_seconds(seconds_remaining)}**.",
        color=0xFF9800,
    )


def failure_embed(message: str) -> discord.Embed:
    return discord.Embed(title="Cannot do that", description=message, color=0xF44336)


def info_embed(message: str) -> discord.Embed:
    return discord.Embed(description=message, color=0x607D8B)


def profile_embed(user: User, champ_count: int, loadout_size: int) -> discord.Embed:
    unlocks = unlocks_for(user.level)
    next_xp = xp_to_next_level(user.level)
    xp_line = f"{user.xp:,} / {next_xp:,}" if next_xp else "MAX"
    lines = [
        f"**Level:** {user.level}    **XP:** {xp_line}",
        f"**Prestige:** {user.prestige}",
        f"**Gold:** {user.gold:,}",
        f"**Champions owned:** {champ_count}",
        f"**Loadout:** {loadout_size} / {unlocks.loadout_slots}",
        f"**Action tiers unlocked:** T1 — T{unlocks.max_action_tier}",
    ]
    return discord.Embed(
        title=f"Profile",
        description="\n".join(lines),
        color=0x3F51B5,
    )


def inventory_embed(items: dict[str, int]) -> discord.Embed:
    if not items:
        return discord.Embed(title="Inventory", description="_empty_", color=0x607D8B)
    # Group sensibly.
    groups = {
        "Tokens": ["roll_token"],
        "Shields": ["shield_physical", "shield_magic", "aegis", "stasis"],
        "Fragments": [f"fragment_t{t}" for t in range(1, 7)],
        "Materials": ["mat", "soul", "corruption_stack", "kindred_passive"],
    }
    lines: list[str] = []
    for header, keys in groups.items():
        present = [(ITEM_LABELS.get(k, k), items.get(k, 0)) for k in keys if items.get(k, 0) > 0]
        if present:
            lines.append(f"**{header}**")
            for label, qty in present:
                lines.append(f"  {label}: {qty}")
    if not lines:
        return discord.Embed(title="Inventory", description="_empty_", color=0x607D8B)
    return discord.Embed(title="Inventory", description="\n".join(lines), color=0x607D8B)


def loadout_embed(entries: list[LoadoutEntry], cap: int) -> discord.Embed:
    if not entries:
        desc = f"_no champions equipped_\n\nSlots available: {cap}"
    else:
        rows: list[str] = []
        for slot in range(1, cap + 1):
            slot_entries = [e for e in entries if e.slot == slot]
            if slot_entries:
                c = slot_entries[0].champion
                rows.append(
                    f"**Slot {slot}:** {c.name} — {TIER_NAME[c.tier]} ({c.damage_type})"
                )
            else:
                rows.append(f"**Slot {slot}:** _empty_")
        desc = "\n".join(rows)
    return discord.Embed(title="Loadout", description=desc, color=0x3F51B5)


def skirmish_embed(
    attacker: discord.abc.User,
    defender: discord.abc.User,
    result: SkirmishResult,
    gold_transferred: int,
) -> discord.Embed:
    lines: list[str] = []
    for i, r in enumerate(result.rounds, start=1):
        winner_label = attacker.display_name if r.attacker_won else defender.display_name
        lines.append(f"**Round {i}** — winner: **{winner_label}**\n{r.flavor}")
    winner = attacker if result.attacker_won else defender
    color = 0x4CAF50 if result.attacker_won else 0xF44336
    final = (
        f"\n\n**{winner.display_name} wins!** "
        f"({result.rounds_won_by_attacker}–{result.rounds_won_by_defender})"
    )
    if gold_transferred:
        final += f"\nGold transferred: **{gold_transferred:,}**"
    return discord.Embed(
        title=f"⚔ {attacker.display_name} vs {defender.display_name}",
        description="\n\n".join(lines) + final,
        color=color,
    )


def trade_embed(trade: Trade, offered: Champion, requested: Champion) -> discord.Embed:
    desc = (
        f"**Trade #{trade.id}** — status: `{trade.status}`\n\n"
        f"Initiator <@{trade.initiator_id}> offers: **{offered.name}** ({TIER_NAME[offered.tier]})\n"
        f"Target <@{trade.target_id}> would give: **{requested.name}** ({TIER_NAME[requested.tier]})\n\n"
        f"Expires: <t:{int(trade.expires_at.timestamp())}:R>"
    )
    return discord.Embed(title="Trade", description=desc, color=0x9C27B0)


# --- PVE embeds --------------------------------------------------------------


def encounter_embed(camp, champ, win_pct: float) -> discord.Embed:
    """Pre-engage card with the camp + your best champ + win% preview."""
    tier_color = TIER_COLOR.get(camp.tier, 0x607D8B)
    flavor = camp.flavor or f"You stumble upon **{camp.name}**."
    weakness_text = f" · weak to {camp.weak_to}" if camp.weak_to else ""
    lines = [
        f"🌲 {flavor}",
        "",
        f"**{camp.name}** — Tier {camp.tier}{weakness_text}",
    ]
    if champ is None:
        lines.append("\nYou have no alive champion — backing out is your only option.")
    else:
        # estimate respawn duration so the player sees the loss cost up front
        diff = max(-4, min(4, champ.tier - camp.tier))
        from bot.game.pve.combat import (
            DEFAULT_RESPAWN_SEC,
            FAIL_GOLD_PCT,
            RESPAWN_DURATION_SEC,
        )
        respawn = RESPAWN_DURATION_SEC.get(diff, DEFAULT_RESPAWN_SEC)
        gold_loss = int(camp.base_gold * FAIL_GOLD_PCT)
        lines += [
            f"Your best alive champion: **{champ.name}** (T{champ.tier}, {champ.damage_type})",
            f"Estimated win chance: **{win_pct:.1f}%**",
            f"On failure: lose ~{gold_loss}g, {champ.name} dies for **{respawn // 60} min**.",
            "",
            "Choose carefully — backing out *also* triggers the hunt cooldown.",
        ]
    return discord.Embed(
        title="A wild encounter!",
        description="\n".join(lines),
        color=tier_color,
    )


def camp_result_embed(camp, champ, outcome) -> discord.Embed:
    """Post-engage result card."""
    fight = outcome.fight
    if fight.won:
        color = TIER_COLOR.get(camp.tier, 0x4CAF50)
        title = f"✅ Slain — {camp.name}"
        lines = [
            f"**{champ.name}** put down {camp.name}.",
            f"Gold: **+{outcome.gold_awarded:,}** · XP: **+{outcome.xp_awarded}**",
        ]
        if fight.drops:
            drop_text = ", ".join(
                f"{ITEM_LABELS.get(t, t)} ×{q}" for t, q in fight.drops
            )
            lines.append(f"Drops: **{drop_text}**")
        if outcome.leveled_up_to:
            lines.append(f":sparkles: **Level Up! → {outcome.leveled_up_to}** :sparkles:")
        lines.append(f"_Hunt cooldown: {outcome.cooldown_seconds_set}s_")
    else:
        color = 0xF44336
        title = f"💀 Defeated by {camp.name}"
        lines = [
            f"**{champ.name}** fell to {camp.name}.",
            f"Gold lost: **{outcome.gold_awarded:,}**",
            f"**{champ.name}** is dead for **{fight.respawn_seconds // 60} min**.",
            f"_Hunt cooldown: {outcome.cooldown_seconds_set}s_",
        ]
    return discord.Embed(title=title, description="\n".join(lines), color=color)


# --- internals ---------------------------------------------------------------


def _format_seconds(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    if s < 86400:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    return f"{s // 86400}d {(s % 86400) // 3600}h"
