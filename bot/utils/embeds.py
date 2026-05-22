"""Discord embed builders shared across cogs."""
from __future__ import annotations

import discord

from bot.db.queries import Champion, LoadoutEntry, RankedProfile, Trade, User
from bot.game import ranked
from bot.game.actions.runner import ActionSuccess
from bot.game.combat import SkirmishResult
from bot.game.leveling import unlocks_for, xp_to_next_level
from bot.game.ranked_flow import RankedOutcome

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
    "red_buff": "Red Buff (dormant)",
    "red_buff_primed": "🔴 Red Buff (PRIMED)",
    "blue_buff": "Blue Buff (dormant)",
    "blue_buff_primed": "🔵 Blue Buff (PRIMED)",
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
        title = "✨ New champion!"
    embed = discord.Embed(title=title, description=desc, color=TIER_COLOR[champion.tier])
    if champion.splash_url:
        if was_dupe:
            # Smaller thumbnail for dupes — less attention-grabbing.
            from bot.utils.champion_images import tile_url
            embed.set_thumbnail(url=tile_url(champion.name))
        else:
            # New pull: full splash, banner-style.
            embed.set_image(url=champion.splash_url)
    return embed


def action_result_embed(success: ActionSuccess) -> discord.Embed:
    spec = success.spec
    lines = [f"**{spec.name}** — {spec.description}"]
    if success.chosen_champion_name:
        lines.append(f"_Performed by_ **{success.chosen_champion_name}**")
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
    embed = discord.Embed(
        title="Action complete",
        description="\n".join(lines),
        color=TIER_COLOR[spec.tier],
    )
    if success.chosen_champion_name:
        from bot.utils.champion_images import tile_url
        embed.set_thumbnail(url=tile_url(success.chosen_champion_name))
    return embed


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


def skirmish_embeds(
    attacker: discord.abc.User,
    defender: discord.abc.User,
    result: SkirmishResult,
    gold_transferred: int,
) -> list[discord.Embed]:
    """Returns a list of 3 embeds rendering the skirmish:
      [0] Match summary with rounds + winner
      [1] Attacker card with lead champion icon
      [2] Defender card with lead champion icon

    Send via `await interaction.response.send_message(embeds=[...])`.
    """
    from bot.utils.champion_images import tile_url

    color = 0x4CAF50 if result.attacker_won else 0xF44336

    # Main summary embed
    lines: list[str] = []
    for i, r in enumerate(result.rounds, start=1):
        winner_label = attacker.display_name if r.attacker_won else defender.display_name
        lines.append(f"**Round {i}** — winner: **{winner_label}**\n{r.flavor}")
    winner = attacker if result.attacker_won else defender
    final = (
        f"\n\n**{winner.display_name} wins!** "
        f"({result.rounds_won_by_attacker}–{result.rounds_won_by_defender})"
    )
    if gold_transferred:
        final += f"\nGold transferred: **{gold_transferred:,}**"
    summary = discord.Embed(
        title=f"⚔ {attacker.display_name} vs {defender.display_name}",
        description="\n\n".join(lines) + final,
        color=color,
    )

    # Lead champions from round 1
    lead_atk = result.rounds[0].attacker_champ if result.rounds else None
    lead_def = result.rounds[0].defender_champ if result.rounds else None

    atk_color = 0x4CAF50 if result.attacker_won else 0x9E9E9E
    atk_embed = discord.Embed(
        title=f"🛡 Attacker — {attacker.display_name}",
        description=(
            f"Lead: **{lead_atk.name}**\n"
            f"T{lead_atk.tier} {lead_atk.damage_type}"
            if lead_atk else "—"
        ),
        color=atk_color,
    )
    if lead_atk:
        atk_embed.set_thumbnail(url=tile_url(lead_atk.name))

    def_color = 0x4CAF50 if not result.attacker_won else 0x9E9E9E
    def_embed = discord.Embed(
        title=f"🛡 Defender — {defender.display_name}",
        description=(
            f"Lead: **{lead_def.name}**\n"
            f"T{lead_def.tier} {lead_def.damage_type}"
            if lead_def else "—"
        ),
        color=def_color,
    )
    if lead_def:
        def_embed.set_thumbnail(url=tile_url(lead_def.name))

    return [summary, atk_embed, def_embed]


# Backwards-compat alias — old callers expect a single embed. Returns just
# the summary so it still renders even without the new dual-icon look.
def skirmish_embed(
    attacker: discord.abc.User,
    defender: discord.abc.User,
    result: SkirmishResult,
    gold_transferred: int,
) -> discord.Embed:
    return skirmish_embeds(attacker, defender, result, gold_transferred)[0]


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
    embed = discord.Embed(
        title="A wild encounter!",
        description="\n".join(lines),
        color=tier_color,
    )
    if champ is not None:
        from bot.utils.champion_images import tile_url
        embed.set_thumbnail(url=tile_url(champ.name))
    return embed


def world_boss_embed(boss, spec, top_strikers, you_dealt) -> discord.Embed:
    """Status embed for an active world boss."""
    name = spec.name if spec else boss.boss_key
    hp_pct = int(round(100 * boss.hp_remaining / max(1, boss.hp_total)))
    lines = [
        f"**HP:** {boss.hp_remaining:,} / {boss.hp_total:,} ({hp_pct}%)",
        f"**Expires:** <t:{int(boss.expires_at.timestamp())}:R>",
    ]
    if top_strikers:
        lines.append("")
        lines.append("**Top strikers:**")
        for i, (uid, dmg) in enumerate(top_strikers):
            lines.append(f"  {i + 1}. <@{uid}> — {dmg:,}")
    lines.append("")
    if you_dealt > 0:
        lines.append(f"_You've dealt {you_dealt:,} damage._")
    else:
        lines.append("_You haven't struck this boss yet — use `/strike`._")
    return discord.Embed(
        title=f"🐉 {name}",
        description="\n".join(lines),
        color=0xFFD700 if hp_pct > 50 else (0xFF9800 if hp_pct > 20 else 0xF44336),
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
    embed = discord.Embed(title=title, description="\n".join(lines), color=color)
    from bot.utils.champion_images import tile_url
    embed.set_thumbnail(url=tile_url(champ.name))
    return embed


# --- Ranked embeds -----------------------------------------------------------

RANK_EMOJI: dict[str, str] = {
    "Iron": "⚙️",
    "Bronze": "🥉",
    "Silver": "🥈",
    "Gold": "🥇",
    "Platinum": "💠",
    "Diamond": "💎",
    "Master": "🔮",
    "Grandmaster": "👑",
    "Challenger": "🏆",
}

RANK_COLOR: dict[str, int] = {
    "Iron": 0x5C5C5C,
    "Bronze": 0x8C6239,
    "Silver": 0x9FA8B0,
    "Gold": 0xF1C40F,
    "Platinum": 0x1ABC9C,
    "Diamond": 0x3498DB,
    "Master": 0x9B59B6,
    "Grandmaster": 0xE74C3C,
    "Challenger": 0xF39C12,
}


def _rank_label(profile: RankedProfile) -> str:
    """Short rank descriptor, e.g. '🥇 Gold · 640 LP'."""
    if profile.in_placements:
        return f"Unranked · placements {profile.placement_games}/5"
    name = ranked.tier_name(profile.lp)
    return f"{RANK_EMOJI.get(name, '')} {name} · {profile.lp} LP"


def _ranked_progress_line(
    name: str,
    profile: RankedProfile,
    lp_delta: int,
    completed_placements: bool,
) -> str:
    if completed_placements:
        return f"**{name}** — placements complete → {_rank_label(profile)}"
    if profile.in_placements:
        return f"**{name}** — placements {profile.placement_games}/5 _(no LP yet)_"
    delta = f"+{lp_delta}" if lp_delta >= 0 else str(lp_delta)
    return f"**{name}** — {_rank_label(profile)}  _({delta} LP)_"


def attack_panel_embed(
    attacker_name: str,
    target_name: str,
    alive_loadout: list[LoadoutEntry],
    heist_note: str,
    raid_note: str,
) -> discord.Embed:
    """The /attack control panel — shows the attacker's champions + options."""
    if alive_loadout:
        champ_lines = "\n".join(
            f"  Slot {e.slot}: **{e.champion.name}** "
            f"(T{e.champion.tier} {e.champion.damage_type})"
            for e in alive_loadout
        )
    else:
        champ_lines = "  _no alive champions — check /menu for revive timers_"
    lines = [
        f"Target: **{target_name}**",
        "",
        "**Your champions**",
        champ_lines,
        "",
        "**⚔️ Ranked Match** — best-of-3 skirmish, moves League Points.",
        "**🗡️ Unranked Duel** — single round, small gold stake.",
        "**🃏 Prank** — steal a sliver of their gold.",
    ]
    if heist_note:
        lines.append(f"_💰 Heist — {heist_note}_")
    if raid_note:
        lines.append(f"_🔥 Raid — {raid_note}_")
    return discord.Embed(
        title=f"⚔️ Attack — {attacker_name}",
        description="\n".join(lines),
        color=0xF44336,
    )


def ranked_result_embeds(
    attacker: discord.abc.User,
    defender: discord.abc.User,
    outcome: RankedOutcome,
) -> list[discord.Embed]:
    """Summary + attacker/defender champion cards for a finished ranked match."""
    skirmish = outcome.skirmish
    color = 0x4CAF50 if outcome.attacker_won else 0xF44336

    lines: list[str] = []
    for i, r in enumerate(skirmish.rounds, start=1):
        winner_label = attacker.display_name if r.attacker_won else defender.display_name
        lines.append(f"**Round {i}** — winner: **{winner_label}**\n{r.flavor}")
    winner = attacker if outcome.attacker_won else defender
    body = "\n\n".join(lines)
    body += (
        f"\n\n**{winner.display_name} wins the skirmish!** "
        f"({skirmish.rounds_won_by_attacker}–{skirmish.rounds_won_by_defender})"
    )
    body += "\n\n__League Points__\n"
    body += _ranked_progress_line(
        attacker.display_name, outcome.attacker_profile,
        outcome.attacker_lp_delta, outcome.attacker_completed_placements,
    )
    body += "\n" + _ranked_progress_line(
        defender.display_name, outcome.defender_profile,
        outcome.defender_lp_delta, outcome.defender_completed_placements,
    )

    summary = discord.Embed(
        title=f"⚔️ Ranked — {attacker.display_name} vs {defender.display_name}",
        description=body,
        color=color,
    )
    # Reuse the champion icon cards from the skirmish renderer.
    cards = skirmish_embeds(attacker, defender, skirmish, 0)[1:]
    return [summary, *cards]


def rank_card_embed(display_name: str, profile: RankedProfile) -> discord.Embed:
    """Personal rank card for /rank."""
    if profile.in_placements:
        losses = profile.placement_games - profile.placement_wins
        desc = (
            f"**Placement matches:** {profile.placement_games} / 5\n"
            f"Record so far: **{profile.placement_wins}W** · **{losses}L**\n\n"
            f"_Finish all 5 placements to be seeded into a rank._"
        )
        return discord.Embed(
            title=f"Rank — {display_name}", description=desc, color=0x607D8B
        )

    name = ranked.tier_name(profile.lp)
    floor = ranked.next_tier_floor(profile.lp)
    progress = (
        f"{floor - profile.lp} LP to the next tier"
        if floor is not None
        else "Top of the ladder — Challenger"
    )
    total = profile.wins + profile.losses
    winrate = f"{round(100 * profile.wins / total)}%" if total else "—"
    lines = [
        f"**{RANK_EMOJI.get(name, '')} {name}** — **{profile.lp} LP**",
        f"_{progress}_",
        "",
        f"Wins: **{profile.wins}** · Losses: **{profile.losses}** · Win rate: **{winrate}**",
    ]
    if profile.win_streak >= 2:
        lines.append(f"🔥 On a **{profile.win_streak}-win** streak")
    elif profile.loss_streak >= 2:
        lines.append(f"❄️ On a **{profile.loss_streak}-loss** streak")
    return discord.Embed(
        title=f"Rank — {display_name}",
        description="\n".join(lines),
        color=RANK_COLOR.get(name, 0x3F51B5),
    )


def leaderboard_embed(rows: list[tuple[int, str, RankedProfile]]) -> discord.Embed:
    """`rows` is (position, display_name_or_mention, profile), already sorted."""
    if not rows:
        return discord.Embed(
            title="🏆 Ranked Leaderboard",
            description="_No players have finished placements yet._",
            color=0xFFC107,
        )
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines: list[str] = []
    for pos, display, p in rows:
        marker = medals.get(pos, f"`#{pos}`")
        name = ranked.tier_name(p.lp)
        lines.append(
            f"{marker} {display} — {RANK_EMOJI.get(name, '')} **{name}** · "
            f"{p.lp} LP _({p.wins}W/{p.losses}L)_"
        )
    return discord.Embed(
        title="🏆 Ranked Leaderboard",
        description="\n".join(lines),
        color=0xFFC107,
    )


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
