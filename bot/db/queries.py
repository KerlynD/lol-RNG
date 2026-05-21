"""Data-access layer.

Convention:
- Single-statement helpers acquire from the pool themselves.
- Multi-statement / atomic operations (e.g. trade accept, pull resolution)
  take a `conn: asyncpg.Connection` so the caller controls the transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import asyncpg

from bot.db.pool import get_pool

STARTER_ROLL_TOKENS = 1


# ----------------------------------------------------------------------------
# Dataclasses
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class User:
    discord_id: int
    gold: int
    xp: int
    level: int
    prestige: int
    starter_token_granted: bool
    last_loadout_swap: datetime | None
    ambient_events_opt_in: bool = False


@dataclass(frozen=True)
class Champion:
    id: int
    name: str
    tier: int
    region: str | None
    factions: list[str]
    damage_type: str
    drop_weight: float
    splash_url: str | None


@dataclass(frozen=True)
class OwnedChampion:
    champion: Champion
    locked: bool
    acquired_at: datetime


@dataclass(frozen=True)
class LoadoutEntry:
    slot: int
    champion: Champion


@dataclass(frozen=True)
class Trade:
    id: int
    initiator_id: int
    target_id: int
    offered_champion_id: int
    requested_champion_id: int
    status: str
    created_at: datetime
    expires_at: datetime
    resolved_at: datetime | None


# ----------------------------------------------------------------------------
# Champion helpers (read-only, cached lightly via DB)
# ----------------------------------------------------------------------------


def _row_to_champion(row: asyncpg.Record) -> Champion:
    return Champion(
        id=row["id"],
        name=row["name"],
        tier=row["tier"],
        region=row["region"],
        factions=list(row["factions"] or []),
        damage_type=row["damage_type"],
        drop_weight=row["drop_weight"],
        splash_url=row["splash_url"],
    )


async def get_champion_by_id(champion_id: int) -> Champion | None:
    row = await get_pool().fetchrow("SELECT * FROM champions WHERE id = $1", champion_id)
    return _row_to_champion(row) if row else None


async def get_champion_by_name(name: str) -> Champion | None:
    row = await get_pool().fetchrow(
        "SELECT * FROM champions WHERE LOWER(name) = LOWER($1)", name
    )
    return _row_to_champion(row) if row else None


async def list_champions_by_tier(tier: int) -> list[Champion]:
    rows = await get_pool().fetch("SELECT * FROM champions WHERE tier = $1", tier)
    return [_row_to_champion(r) for r in rows]


async def get_all_champions() -> list[Champion]:
    rows = await get_pool().fetch("SELECT * FROM champions ORDER BY tier, name")
    return [_row_to_champion(r) for r in rows]


# ----------------------------------------------------------------------------
# Users
# ----------------------------------------------------------------------------


def _row_to_user(row: asyncpg.Record) -> User:
    keys = row.keys()
    return User(
        discord_id=row["discord_id"],
        gold=row["gold"],
        xp=row["xp"],
        level=row["level"],
        prestige=row["prestige"],
        starter_token_granted=row["starter_token_granted"],
        last_loadout_swap=row["last_loadout_swap"],
        ambient_events_opt_in=row["ambient_events_opt_in"] if "ambient_events_opt_in" in keys else False,
    )


async def ensure_user(discord_id: int) -> User:
    """Create user if missing. Grants 1 Roll Token on first creation (PRD §8.1)."""
    p = get_pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM users WHERE discord_id = $1 FOR UPDATE", discord_id
            )
            if row is None:
                row = await conn.fetchrow(
                    """
                    INSERT INTO users (discord_id, starter_token_granted)
                    VALUES ($1, TRUE)
                    RETURNING *
                    """,
                    discord_id,
                )
                await conn.execute(
                    """
                    INSERT INTO inventory (user_id, item_type, quantity)
                    VALUES ($1, 'roll_token', $2)
                    ON CONFLICT (user_id, item_type)
                    DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity
                    """,
                    discord_id, STARTER_ROLL_TOKENS,
                )
            elif not row["starter_token_granted"]:
                # Edge case: user row exists (e.g. from PvP backref) without token.
                await conn.execute(
                    "UPDATE users SET starter_token_granted = TRUE WHERE discord_id = $1",
                    discord_id,
                )
                await conn.execute(
                    """
                    INSERT INTO inventory (user_id, item_type, quantity)
                    VALUES ($1, 'roll_token', $2)
                    ON CONFLICT (user_id, item_type)
                    DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity
                    """,
                    discord_id, STARTER_ROLL_TOKENS,
                )
                row = await conn.fetchrow("SELECT * FROM users WHERE discord_id = $1", discord_id)
            return _row_to_user(row)


async def get_user(discord_id: int) -> User | None:
    row = await get_pool().fetchrow("SELECT * FROM users WHERE discord_id = $1", discord_id)
    return _row_to_user(row) if row else None


async def add_gold(discord_id: int, amount: int, *, conn: asyncpg.Connection | None = None) -> int:
    """Add (or subtract, if negative) gold. Returns new balance."""
    query = """
        UPDATE users SET gold = GREATEST(0, gold + $2)
         WHERE discord_id = $1
         RETURNING gold
    """
    if conn is not None:
        return await conn.fetchval(query, discord_id, amount)
    return await get_pool().fetchval(query, discord_id, amount)


async def set_user_level_xp(
    discord_id: int, new_level: int, new_xp: int, *, conn: asyncpg.Connection | None = None
) -> None:
    query = "UPDATE users SET level = $2, xp = $3 WHERE discord_id = $1"
    if conn is not None:
        await conn.execute(query, discord_id, new_level, new_xp)
    else:
        await get_pool().execute(query, discord_id, new_level, new_xp)


async def reset_for_prestige(discord_id: int) -> None:
    """Wipe XP/level/loadouts/owned champs; keep currencies & items; bump prestige."""
    p = get_pool()
    async with p.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM loadouts WHERE user_id = $1", discord_id)
            await conn.execute("DELETE FROM user_champions WHERE user_id = $1", discord_id)
            await conn.execute(
                """
                UPDATE users
                   SET xp = 0,
                       level = 1,
                       prestige = prestige + 1,
                       last_loadout_swap = NULL
                 WHERE discord_id = $1
                """,
                discord_id,
            )


# ----------------------------------------------------------------------------
# Ownership
# ----------------------------------------------------------------------------


async def own_champion(
    discord_id: int, champion_id: int, *, conn: asyncpg.Connection | None = None
) -> bool:
    """Insert ownership. Returns True if newly owned, False if it was a dupe."""
    query = """
        INSERT INTO user_champions (user_id, champion_id)
        VALUES ($1, $2)
        ON CONFLICT (user_id, champion_id) DO NOTHING
        RETURNING user_id
    """
    if conn is not None:
        row = await conn.fetchrow(query, discord_id, champion_id)
    else:
        row = await get_pool().fetchrow(query, discord_id, champion_id)
    return row is not None


async def list_owned(discord_id: int) -> list[OwnedChampion]:
    rows = await get_pool().fetch(
        """
        SELECT c.*, uc.locked, uc.acquired_at
          FROM user_champions uc
          JOIN champions c ON c.id = uc.champion_id
         WHERE uc.user_id = $1
         ORDER BY c.tier DESC, c.name
        """,
        discord_id,
    )
    return [
        OwnedChampion(
            champion=_row_to_champion(r),
            locked=r["locked"],
            acquired_at=r["acquired_at"],
        )
        for r in rows
    ]


async def owns_champion(discord_id: int, champion_id: int) -> bool:
    val = await get_pool().fetchval(
        "SELECT 1 FROM user_champions WHERE user_id = $1 AND champion_id = $2",
        discord_id, champion_id,
    )
    return val is not None


async def set_locked(discord_id: int, champion_id: int, locked: bool) -> bool:
    """Toggle lock state. Returns True if a row was updated."""
    res = await get_pool().execute(
        "UPDATE user_champions SET locked = $3 WHERE user_id = $1 AND champion_id = $2",
        discord_id, champion_id, locked,
    )
    return res.endswith(" 1")


async def is_locked(discord_id: int, champion_id: int) -> bool:
    val = await get_pool().fetchval(
        "SELECT locked FROM user_champions WHERE user_id = $1 AND champion_id = $2",
        discord_id, champion_id,
    )
    return bool(val)


async def remove_champion(
    discord_id: int, champion_id: int, *, conn: asyncpg.Connection | None = None
) -> bool:
    """Used for sacrifice / trade. Returns True if a row was deleted."""
    query = "DELETE FROM user_champions WHERE user_id = $1 AND champion_id = $2 RETURNING 1"
    if conn is not None:
        val = await conn.fetchval(query, discord_id, champion_id)
    else:
        val = await get_pool().fetchval(query, discord_id, champion_id)
    return val is not None


# ----------------------------------------------------------------------------
# Loadout
# ----------------------------------------------------------------------------


async def get_loadout(discord_id: int) -> list[LoadoutEntry]:
    rows = await get_pool().fetch(
        """
        SELECT l.slot, c.*
          FROM loadouts l
          JOIN champions c ON c.id = l.champion_id
         WHERE l.user_id = $1
         ORDER BY l.slot
        """,
        discord_id,
    )
    return [LoadoutEntry(slot=r["slot"], champion=_row_to_champion(r)) for r in rows]


# ----------------------------------------------------------------------------
# Champion respawn (PVE death system, PRD v2)
# ----------------------------------------------------------------------------
# Champion respawn cooldowns ride on the existing `cooldowns` table using the
# convention `action_key = '_champ:{champion_id}'`. A champion is "dead" if a
# cooldown with that key exists with available_at > NOW().

CHAMP_RESPAWN_PREFIX = "_champ:"


def _champ_respawn_key(champion_id: int) -> str:
    return f"{CHAMP_RESPAWN_PREFIX}{champion_id}"


async def kill_champion(
    discord_id: int, champion_id: int, duration: timedelta,
    *, conn: asyncpg.Connection | None = None,
) -> None:
    """Stamp a respawn cooldown for the given champion."""
    until = datetime.now(tz=timezone.utc) + duration
    query = """
        INSERT INTO cooldowns (user_id, action_key, available_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, action_key)
        DO UPDATE SET available_at = EXCLUDED.available_at
    """
    if conn is not None:
        await conn.execute(query, discord_id, _champ_respawn_key(champion_id), until)
    else:
        await get_pool().execute(query, discord_id, _champ_respawn_key(champion_id), until)


async def champion_is_alive(discord_id: int, champion_id: int) -> bool:
    """Returns True if the champion has no active respawn cooldown."""
    row = await get_pool().fetchrow(
        "SELECT available_at FROM cooldowns WHERE user_id = $1 AND action_key = $2",
        discord_id, _champ_respawn_key(champion_id),
    )
    if row is None:
        return True
    return row["available_at"] <= datetime.now(tz=timezone.utc)


async def alive_loadout(discord_id: int) -> list[LoadoutEntry]:
    """Same as get_loadout but skips champions in respawn cooldown."""
    rows = await get_pool().fetch(
        """
        SELECT l.slot, c.*
          FROM loadouts l
          JOIN champions c ON c.id = l.champion_id
          LEFT JOIN cooldowns cd
                 ON cd.user_id = l.user_id
                AND cd.action_key = '_champ:' || c.id::text
                AND cd.available_at > NOW()
         WHERE l.user_id = $1 AND cd.action_key IS NULL
         ORDER BY l.slot
        """,
        discord_id,
    )
    return [LoadoutEntry(slot=r["slot"], champion=_row_to_champion(r)) for r in rows]


# ----------------------------------------------------------------------------
# World bosses (PRD v2 Phase B)
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class WorldBoss:
    id: int
    boss_key: str
    channel_id: int
    hp_total: int
    hp_remaining: int
    status: str
    spawned_at: datetime
    expires_at: datetime
    resolved_at: datetime | None


def _row_to_world_boss(row: asyncpg.Record) -> WorldBoss:
    return WorldBoss(
        id=row["id"],
        boss_key=row["boss_key"],
        channel_id=row["channel_id"],
        hp_total=row["hp_total"],
        hp_remaining=row["hp_remaining"],
        status=row["status"],
        spawned_at=row["spawned_at"],
        expires_at=row["expires_at"],
        resolved_at=row["resolved_at"],
    )


async def spawn_world_boss(
    boss_key: str, channel_id: int, hp_total: int, duration: timedelta
) -> WorldBoss:
    expires_at = datetime.now(tz=timezone.utc) + duration
    row = await get_pool().fetchrow(
        """
        INSERT INTO world_bosses (boss_key, channel_id, hp_total, hp_remaining, expires_at)
        VALUES ($1, $2, $3, $3, $4)
        RETURNING *
        """,
        boss_key, channel_id, hp_total, expires_at,
    )
    return _row_to_world_boss(row)


async def get_active_world_boss() -> WorldBoss | None:
    row = await get_pool().fetchrow(
        "SELECT * FROM world_bosses WHERE status = 'active' ORDER BY spawned_at DESC LIMIT 1"
    )
    return _row_to_world_boss(row) if row else None


async def apply_strike(boss_id: int, attacker_id: int, damage: int) -> tuple[int, bool]:
    """Atomically apply damage to a boss. Returns (new_hp_remaining, defeated).

    Returns (-1, False) if the boss is no longer active.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE world_bosses
                   SET hp_remaining = GREATEST(0, hp_remaining - $2)
                 WHERE id = $1 AND status = 'active'
                 RETURNING hp_remaining
                """,
                boss_id, damage,
            )
            if row is None:
                return -1, False
            new_hp = row["hp_remaining"]
            actual_damage = damage if new_hp > 0 else damage  # caller knows base damage
            await conn.execute(
                """
                INSERT INTO world_boss_damage (boss_id, user_id, damage_dealt)
                VALUES ($1, $2, $3)
                ON CONFLICT (boss_id, user_id)
                DO UPDATE SET damage_dealt = world_boss_damage.damage_dealt + $3,
                              last_strike_at = NOW()
                """,
                boss_id, attacker_id, actual_damage,
            )
            defeated = new_hp <= 0
            if defeated:
                await conn.execute(
                    "UPDATE world_bosses SET status = 'defeated', resolved_at = NOW() WHERE id = $1",
                    boss_id,
                )
    return new_hp, defeated


async def list_top_strikers(boss_id: int, limit: int = 5) -> list[tuple[int, int]]:
    """Returns (user_id, damage_dealt) ordered by damage desc."""
    rows = await get_pool().fetch(
        """
        SELECT user_id, damage_dealt FROM world_boss_damage
         WHERE boss_id = $1
         ORDER BY damage_dealt DESC
         LIMIT $2
        """,
        boss_id, limit,
    )
    return [(r["user_id"], r["damage_dealt"]) for r in rows]


async def expire_old_world_bosses() -> list[WorldBoss]:
    """Mark active bosses past expires_at as expired. Returns the bosses that just expired."""
    rows = await get_pool().fetch(
        """
        UPDATE world_bosses
           SET status = 'expired', resolved_at = NOW()
         WHERE status = 'active' AND expires_at <= NOW()
         RETURNING *
        """,
    )
    return [_row_to_world_boss(r) for r in rows]


# Server config (per-server key/value store; v2 = single-server bot so this
# IS server-wide).


async def get_config(key: str) -> str | None:
    return await get_pool().fetchval("SELECT value FROM server_config WHERE key = $1", key)


async def set_config(key: str, value: str) -> None:
    await get_pool().execute(
        """
        INSERT INTO server_config (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        key, value,
    )


# Activity-based count for HP scaling.


async def active_users_last_7d() -> int:
    """Distinct users who set any non-internal cooldown in the last 7 days."""
    val = await get_pool().fetchval(
        """
        SELECT COUNT(DISTINCT user_id) FROM cooldowns
         WHERE NOT action_key LIKE '\\_%' ESCAPE '\\'
           AND available_at > NOW() - INTERVAL '7 days'
        """
    )
    return val or 0


async def get_strike_cooldown(user_id: int, boss_id: int) -> float | None:
    """Returns seconds remaining on a per-user, per-boss strike cooldown."""
    return await check_cooldown(user_id, f"_strike:{boss_id}")


async def set_strike_cooldown(user_id: int, boss_id: int, duration: timedelta) -> None:
    await set_cooldown(user_id, f"_strike:{boss_id}", duration)


# ----------------------------------------------------------------------------
# Ambient events (PRD v2 Phase B)
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class AmbientEvent:
    id: int
    target_id: int
    channel_id: int
    message_id: int | None
    event_type: str
    status: str
    spawned_at: datetime
    expires_at: datetime
    resolved_at: datetime | None


def _row_to_ambient(row: asyncpg.Record) -> AmbientEvent:
    return AmbientEvent(
        id=row["id"],
        target_id=row["target_id"],
        channel_id=row["channel_id"],
        message_id=row["message_id"],
        event_type=row["event_type"],
        status=row["status"],
        spawned_at=row["spawned_at"],
        expires_at=row["expires_at"],
        resolved_at=row["resolved_at"],
    )


async def set_ambient_opt_in(discord_id: int, opt_in: bool) -> None:
    await get_pool().execute(
        "UPDATE users SET ambient_events_opt_in = $2 WHERE discord_id = $1",
        discord_id, opt_in,
    )


async def list_opted_in_active_users(
    *, active_days: int = 7, ambient_cooldown_min: int = 20
) -> list[int]:
    """Users opted in, with recent activity, and no pending event AND no event in last 20 min."""
    rows = await get_pool().fetch(
        """
        SELECT u.discord_id FROM users u
         WHERE u.ambient_events_opt_in = TRUE
           AND EXISTS (
                 SELECT 1 FROM cooldowns c
                  WHERE c.user_id = u.discord_id
                    AND NOT c.action_key LIKE '\\_%' ESCAPE '\\'
                    AND c.available_at > NOW() - ($1::int || ' days')::interval
               )
           AND NOT EXISTS (
                 SELECT 1 FROM ambient_events e
                  WHERE e.target_id = u.discord_id
                    AND (
                          e.status = 'pending'
                       OR e.resolved_at > NOW() - ($2::int || ' minutes')::interval
                    )
               )
        """,
        active_days, ambient_cooldown_min,
    )
    return [r["discord_id"] for r in rows]


async def create_ambient_event(
    target_id: int, channel_id: int, event_type: str, ttl: timedelta
) -> AmbientEvent:
    expires_at = datetime.now(tz=timezone.utc) + ttl
    row = await get_pool().fetchrow(
        """
        INSERT INTO ambient_events (target_id, channel_id, event_type, expires_at)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        target_id, channel_id, event_type, expires_at,
    )
    return _row_to_ambient(row)


async def set_ambient_message_id(event_id: int, message_id: int) -> None:
    await get_pool().execute(
        "UPDATE ambient_events SET message_id = $2 WHERE id = $1",
        event_id, message_id,
    )


async def get_ambient_event(event_id: int) -> AmbientEvent | None:
    row = await get_pool().fetchrow("SELECT * FROM ambient_events WHERE id = $1", event_id)
    return _row_to_ambient(row) if row else None


async def resolve_ambient_event(
    event_id: int, status: str, gold: int, xp: int,
    *, conn: asyncpg.Connection | None = None,
) -> bool:
    """Mark event resolved. Returns True if it was previously pending."""
    query = """
        UPDATE ambient_events
           SET status = $2, resolved_at = NOW(), outcome_gold = $3, outcome_xp = $4
         WHERE id = $1 AND status = 'pending'
         RETURNING 1
    """
    if conn is not None:
        val = await conn.fetchval(query, event_id, status, gold, xp)
    else:
        val = await get_pool().fetchval(query, event_id, status, gold, xp)
    return val is not None


async def expire_pending_ambient_events() -> list[AmbientEvent]:
    rows = await get_pool().fetch(
        """
        UPDATE ambient_events
           SET status = 'expired', resolved_at = NOW()
         WHERE status = 'pending' AND expires_at <= NOW()
         RETURNING *
        """,
    )
    return [_row_to_ambient(r) for r in rows]


async def dead_champions_for_user(discord_id: int) -> list[tuple[int, str, float]]:
    """Return (champion_id, name, seconds_remaining) for each dead champion in the user's loadout."""
    rows = await get_pool().fetch(
        """
        SELECT c.id, c.name,
               EXTRACT(EPOCH FROM (cd.available_at - NOW())) AS remaining
          FROM loadouts l
          JOIN champions c ON c.id = l.champion_id
          JOIN cooldowns cd
            ON cd.user_id = l.user_id
           AND cd.action_key = '_champ:' || c.id::text
           AND cd.available_at > NOW()
         WHERE l.user_id = $1
         ORDER BY cd.available_at
        """,
        discord_id,
    )
    return [(r["id"], r["name"], float(r["remaining"])) for r in rows]


async def set_loadout_slot(discord_id: int, slot: int, champion_id: int) -> None:
    await get_pool().execute(
        """
        INSERT INTO loadouts (user_id, slot, champion_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, slot)
        DO UPDATE SET champion_id = EXCLUDED.champion_id
        """,
        discord_id, slot, champion_id,
    )


async def clear_loadout_slot(discord_id: int, slot: int) -> bool:
    res = await get_pool().execute(
        "DELETE FROM loadouts WHERE user_id = $1 AND slot = $2", discord_id, slot
    )
    return res.endswith(" 1")


async def stamp_loadout_swap(discord_id: int) -> None:
    await get_pool().execute(
        "UPDATE users SET last_loadout_swap = NOW() WHERE discord_id = $1", discord_id
    )


# ----------------------------------------------------------------------------
# Inventory
# ----------------------------------------------------------------------------


async def add_item(
    discord_id: int, item_type: str, qty: int, *, conn: asyncpg.Connection | None = None
) -> int:
    """Add (or subtract via negative qty) item. Returns new quantity (clamped to >= 0)."""
    query = """
        INSERT INTO inventory (user_id, item_type, quantity)
        VALUES ($1, $2, GREATEST(0, $3))
        ON CONFLICT (user_id, item_type)
        DO UPDATE SET quantity = GREATEST(0, inventory.quantity + $3)
        RETURNING quantity
    """
    if conn is not None:
        return await conn.fetchval(query, discord_id, item_type, qty)
    return await get_pool().fetchval(query, discord_id, item_type, qty)


async def consume_item(
    discord_id: int, item_type: str, qty: int, *, conn: asyncpg.Connection | None = None
) -> bool:
    """Atomically consume `qty` of an item. Returns True if successful."""
    assert qty > 0
    query = """
        UPDATE inventory
           SET quantity = quantity - $3
         WHERE user_id = $1 AND item_type = $2 AND quantity >= $3
         RETURNING quantity
    """
    if conn is not None:
        val = await conn.fetchval(query, discord_id, item_type, qty)
    else:
        val = await get_pool().fetchval(query, discord_id, item_type, qty)
    return val is not None


async def get_inventory(discord_id: int) -> dict[str, int]:
    rows = await get_pool().fetch(
        "SELECT item_type, quantity FROM inventory WHERE user_id = $1 AND quantity > 0",
        discord_id,
    )
    return {r["item_type"]: r["quantity"] for r in rows}


async def get_item_qty(discord_id: int, item_type: str) -> int:
    val = await get_pool().fetchval(
        "SELECT quantity FROM inventory WHERE user_id = $1 AND item_type = $2",
        discord_id, item_type,
    )
    return val or 0


# ----------------------------------------------------------------------------
# Cooldowns
# ----------------------------------------------------------------------------


async def check_cooldown(discord_id: int, action_key: str) -> float | None:
    """Returns seconds remaining, or None if the action is available."""
    row = await get_pool().fetchrow(
        "SELECT available_at FROM cooldowns WHERE user_id = $1 AND action_key = $2",
        discord_id, action_key,
    )
    if row is None:
        return None
    available_at = row["available_at"]
    now = datetime.now(tz=timezone.utc)
    if available_at <= now:
        return None
    return (available_at - now).total_seconds()


async def get_all_cooldowns(discord_id: int) -> dict[str, float]:
    """One round-trip fetch of every active cooldown for a user.

    Returns {action_key: seconds_remaining}. Stale entries (already elapsed)
    are filtered out.
    """
    rows = await get_pool().fetch(
        "SELECT action_key, available_at FROM cooldowns WHERE user_id = $1",
        discord_id,
    )
    now = datetime.now(tz=timezone.utc)
    out: dict[str, float] = {}
    for r in rows:
        remaining = (r["available_at"] - now).total_seconds()
        if remaining > 0:
            out[r["action_key"]] = remaining
    return out


async def set_cooldown(
    discord_id: int,
    action_key: str,
    duration: timedelta,
    *,
    conn: asyncpg.Connection | None = None,
) -> None:
    until = datetime.now(tz=timezone.utc) + duration
    query = """
        INSERT INTO cooldowns (user_id, action_key, available_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (user_id, action_key)
        DO UPDATE SET available_at = EXCLUDED.available_at
    """
    if conn is not None:
        await conn.execute(query, discord_id, action_key, until)
    else:
        await get_pool().execute(query, discord_id, action_key, until)


async def clear_cooldown(discord_id: int, action_key: str) -> None:
    await get_pool().execute(
        "DELETE FROM cooldowns WHERE user_id = $1 AND action_key = $2",
        discord_id, action_key,
    )


# ----------------------------------------------------------------------------
# PvP
# ----------------------------------------------------------------------------


async def log_pvp(
    attacker_id: int,
    defender_id: int,
    outcome: str,
    gold_transferred: int,
    *,
    conn: asyncpg.Connection | None = None,
) -> None:
    query = """
        INSERT INTO pvp_log (attacker_id, defender_id, outcome, gold_transferred)
        VALUES ($1, $2, $3, $4)
    """
    if conn is not None:
        await conn.execute(query, attacker_id, defender_id, outcome, gold_transferred)
    else:
        await get_pool().execute(query, attacker_id, defender_id, outcome, gold_transferred)


async def count_recent_attacks_received(defender_id: int, hours: int = 24) -> int:
    val = await get_pool().fetchval(
        """
        SELECT COUNT(*) FROM pvp_log
         WHERE defender_id = $1 AND created_at > NOW() - ($2 || ' hours')::interval
        """,
        defender_id, str(hours),
    )
    return val or 0


# ----------------------------------------------------------------------------
# Trades
# ----------------------------------------------------------------------------


def _row_to_trade(row: asyncpg.Record) -> Trade:
    return Trade(
        id=row["id"],
        initiator_id=row["initiator_id"],
        target_id=row["target_id"],
        offered_champion_id=row["offered_champion_id"],
        requested_champion_id=row["requested_champion_id"],
        status=row["status"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        resolved_at=row["resolved_at"],
    )


async def create_trade(
    initiator_id: int,
    target_id: int,
    offered_champion_id: int,
    requested_champion_id: int,
    ttl: timedelta,
) -> Trade:
    expires_at = datetime.now(tz=timezone.utc) + ttl
    row = await get_pool().fetchrow(
        """
        INSERT INTO trades (initiator_id, target_id, offered_champion_id, requested_champion_id, expires_at)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        initiator_id, target_id, offered_champion_id, requested_champion_id, expires_at,
    )
    return _row_to_trade(row)


async def get_trade(trade_id: int) -> Trade | None:
    row = await get_pool().fetchrow("SELECT * FROM trades WHERE id = $1", trade_id)
    return _row_to_trade(row) if row else None


async def list_pending_trades_for_user(discord_id: int) -> list[Trade]:
    rows = await get_pool().fetch(
        """
        SELECT * FROM trades
         WHERE status = 'pending' AND (initiator_id = $1 OR target_id = $1)
         ORDER BY created_at DESC
        """,
        discord_id,
    )
    return [_row_to_trade(r) for r in rows]


async def list_trade_log(discord_id: int, limit: int = 25) -> list[Trade]:
    rows = await get_pool().fetch(
        """
        SELECT * FROM trades
         WHERE initiator_id = $1 OR target_id = $1
         ORDER BY created_at DESC
         LIMIT $2
        """,
        discord_id, limit,
    )
    return [_row_to_trade(r) for r in rows]


async def set_trade_status(
    trade_id: int, status: str, *, conn: asyncpg.Connection | None = None
) -> bool:
    """Sets status and resolved_at. Returns True if a row was updated and was previously pending."""
    query = """
        UPDATE trades
           SET status = $2, resolved_at = NOW()
         WHERE id = $1 AND status = 'pending'
         RETURNING 1
    """
    if conn is not None:
        val = await conn.fetchval(query, trade_id, status)
    else:
        val = await get_pool().fetchval(query, trade_id, status)
    return val is not None


async def expire_old_trades() -> int:
    """Marks pending trades past expires_at as expired. Returns count."""
    res = await get_pool().execute(
        """
        UPDATE trades
           SET status = 'expired', resolved_at = NOW()
         WHERE status = 'pending' AND expires_at <= NOW()
        """,
    )
    # res format: "UPDATE N"
    try:
        return int(res.split()[-1])
    except (IndexError, ValueError):
        return 0


# ----------------------------------------------------------------------------
# Reap marks
# ----------------------------------------------------------------------------


async def set_reap_mark(target_id: int, caster_id: int, ttl: timedelta) -> bool:
    """Returns True if mark was set, False if one already existed (exclusivity per PRD §6.7)."""
    expires_at = datetime.now(tz=timezone.utc) + ttl
    val = await get_pool().fetchval(
        """
        INSERT INTO reap_marks (target_id, caster_id, expires_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (target_id) DO NOTHING
        RETURNING 1
        """,
        target_id, caster_id, expires_at,
    )
    return val is not None


async def get_reap_mark(target_id: int) -> tuple[int, datetime] | None:
    row = await get_pool().fetchrow(
        "SELECT caster_id, expires_at FROM reap_marks WHERE target_id = $1 AND expires_at > NOW()",
        target_id,
    )
    if row is None:
        return None
    return row["caster_id"], row["expires_at"]


async def clear_reap_mark(
    target_id: int, *, conn: asyncpg.Connection | None = None
) -> None:
    query = "DELETE FROM reap_marks WHERE target_id = $1"
    if conn is not None:
        await conn.execute(query, target_id)
    else:
        await get_pool().execute(query, target_id)


async def expire_old_reap_marks() -> int:
    res = await get_pool().execute("DELETE FROM reap_marks WHERE expires_at <= NOW()")
    try:
        return int(res.split()[-1])
    except (IndexError, ValueError):
        return 0


# ----------------------------------------------------------------------------
# Smoke test (kept for /dbcheck)
# ----------------------------------------------------------------------------


async def champion_count() -> int:
    return await get_pool().fetchval("SELECT COUNT(*) FROM champions")
