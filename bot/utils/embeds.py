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


def encounter_embed(
    camp, champ, win_pct: float, *, opponent_splash: str | None = None
) -> discord.Embed:
    """Pre-engage card with the camp + your best champ + win% preview.

    `opponent_splash` — for wild-champion encounters, the champion's splash art
    is shown as the banner image.
    """
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
    if opponent_splash:
        embed.set_image(url=opponent_splash)
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


def camp_result_embed(
    camp, champ, outcome, *, opponent_splash: str | None = None
) -> discord.Embed:
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
    if opponent_splash:
        embed.set_image(url=opponent_splash)
    return embed


# --- Runeterra adventure embeds (v3) -----------------------------------------

# Drop a hosted image of the map of Runeterra here to show it on
# /start-adventure. Left blank ships a clean text map instead.
RUNETERRA_MAP_URL = ""


def _world_map_lines(current_key: str | None, unlocked: set[str]) -> list[str]:
    """A compact text map: ✅ unlocked, 📍 current, 🔒 locked, danger band."""
    from bot.game.world.regions import REGION_ORDER, WORLD, tier_band_label

    lines: list[str] = []
    for key in REGION_ORDER:
        region = WORLD[key]
        if region.hidden and key not in unlocked:
            continue  # the Void stays secret until discovered
        if key == current_key:
            marker = "📍"
        elif key in unlocked:
            marker = "✅"
        else:
            marker = "🔒"
        lines.append(f"{marker} **{region.display}** · {tier_band_label(region)}")
    return lines


def adventure_welcome_embed() -> discord.Embed:
    """Onboarding card shown the first time a player runs /start-adventure."""
    from bot.game.world.regions import get_region

    bandle = get_region("bandle_city")
    desc = (
        "You awaken beneath the **Bandle Tree**, in the hidden dimension of "
        "**Bandle City** — the kindest corner of all creation. Yordles bustle "
        "around you. Somewhere far away, the rest of Runeterra is waiting.\n\n"
        "**How your adventure works:**\n"
        "• `/roll` champions — but only up to your **region's tier**. Bandle "
        "City caps at **Tier 2**, so no day-one Legendaries.\n"
        "• `/hunt-camp` the monsters of whatever region you're standing in.\n"
        "• `/adventure` is your hub — track region goals, travel, and quests.\n"
        "• Complete a region's **goals** to unlock travel to the next region.\n"
        "• The deeper you go, the deadlier it gets — and the richer.\n\n"
        f"_{bandle.blurb if bandle else ''}_"
    )
    embed = discord.Embed(
        title="🌳 Your Adventure Begins — Bandle City",
        description=desc,
        color=0x8BC34A,
    )
    if RUNETERRA_MAP_URL:
        embed.set_image(url=RUNETERRA_MAP_URL)
    embed.set_footer(text="Run /adventure any time to see where you are.")
    return embed


def adventure_hub_embed(
    user: User,
    unlocked: list[str],
    neighbor_goals: dict | None = None,
    travel_cd_remaining: float | None = None,
) -> discord.Embed:
    """The /adventure dashboard — current location, map, reachable regions and
    the unlock-goal checklist for locked neighbors.

    `neighbor_goals` maps a locked region_key -> list[GoalStatus].
    """
    from bot.game.world.regions import (
        WORLD,
        get_region,
        roll_tier_cap,
        tier_band_label,
        travel_cost,
    )

    neighbor_goals = neighbor_goals or {}
    unlocked_set = set(unlocked)
    region = get_region(user.current_region)
    if region is None:
        return failure_embed("You have no location — run /start-adventure.")

    cap = roll_tier_cap(region.key)
    embed = discord.Embed(
        title=f"🧭 Adventure — 📍 {region.display}",
        description=(
            f"_{region.blurb}_\n\n"
            f"**Danger band:** {tier_band_label(region)}  ·  "
            f"**Roll cap:** Tier {cap}\n"
            f"**Gold:** {user.gold:,}  ·  **Level:** {user.level}"
        ),
        color=0x3F51B5,
    )

    for nb_key in region.neighbors:
        nb = WORLD.get(nb_key)
        if nb is None or (nb.hidden and nb_key not in unlocked_set):
            continue
        cost = travel_cost(region.key, nb_key)
        if nb_key in unlocked_set:
            embed.add_field(
                name=f"✅ {nb.display} ({tier_band_label(nb)})",
                value=f"Unlocked — travel for **{cost:,}** Gold.",
                inline=False,
            )
        else:
            statuses = neighbor_goals.get(nb_key, [])
            lines = [
                f"{'✅' if s.done else '⬜'} {s.goal.label}  "
                f"({min(s.current, s.goal.target):,}/{s.goal.target:,})"
                for s in statuses
            ]
            ready = statuses and all(s.done for s in statuses)
            head = "🔓 READY — travel to unlock!" if ready else "🔒 Locked — goals:"
            embed.add_field(
                name=f"{'🔓' if ready else '🔒'} {nb.display} ({tier_band_label(nb)})",
                value=f"{head}\n" + "\n".join(lines) + f"\nTravel cost: **{cost:,}** Gold.",
                inline=False,
            )

    embed.add_field(
        name="🌍 Map of Runeterra",
        value="\n".join(_world_map_lines(region.key, unlocked_set)),
        inline=False,
    )
    if travel_cd_remaining:
        embed.set_footer(
            text=f"✈ Resting from your last journey — {_format_seconds(travel_cd_remaining)} left."
        )
    return embed


def region_arrival_embed(region_key: str) -> discord.Embed:
    """Story beat shown the first time a player unlocks/enters a region — a
    greeting champion with their splash art."""
    from bot.game.world.goals import ARRIVAL
    from bot.game.world.regions import get_region
    from bot.utils.champion_images import splash_url

    region = get_region(region_key)
    display = region.display if region else region_key
    embed = discord.Embed(
        title=f"🌟 A new land — {display}",
        color=0xFFD54F,
    )
    arrival = ARRIVAL.get(region_key)
    if arrival:
        greeter, text = arrival
        embed.description = text
        embed.set_image(url=splash_url(greeter))
        embed.set_author(name=f"{greeter} greets you")
    else:
        embed.description = f"You step through the portal into **{display}**."
    if region:
        embed.set_footer(text=f"{display} is now unlocked. Run /adventure.")
    return embed


def travel_embed(region_key: str, gold_spent: int) -> discord.Embed:
    """Confirmation shown when travelling to an already-unlocked region."""
    from bot.game.world.regions import get_region, tier_band_label

    region = get_region(region_key)
    display = region.display if region else region_key
    band = f" ({tier_band_label(region)})" if region else ""
    return discord.Embed(
        title=f"✈ Travelled to {display}",
        description=(
            f"You arrive in **{display}**{band}.\n"
            f"Journey cost: **{gold_spent:,}** Gold.\n\n"
            f"_{region.blurb if region else ''}_"
        ),
        color=0x3F51B5,
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
