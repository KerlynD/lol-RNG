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
    return User(
        discord_id=row["discord_id"],
        gold=row["gold"],
        xp=row["xp"],
        level=row["level"],
        prestige=row["prestige"],
        starter_token_granted=row["starter_token_granted"],
        last_loadout_swap=row["last_loadout_swap"],
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
