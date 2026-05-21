from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import asyncpg

from bot.config import REPO_ROOT, Settings
from bot.db import pool
from bot.game.seed_weights import assign_drop_weight

log = logging.getLogger(__name__)

MIGRATIONS_DIR = REPO_ROOT / "migrations"
CHAMPIONS_JSON = REPO_ROOT / "data" / "champions.json"


async def _ensure_migrations_table(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


async def _applied_versions(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT version FROM schema_migrations")
    return {r["version"] for r in rows}


async def _apply_sql_migrations(conn: asyncpg.Connection) -> None:
    await _ensure_migrations_table(conn)
    applied = await _applied_versions(conn)

    files = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
    for path in files:
        version = path.stem
        if version in applied:
            log.debug("Skipping migration %s (already applied)", version)
            continue
        log.info("Applying migration %s", version)
        sql = path.read_text(encoding="utf-8")
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations (version) VALUES ($1) ON CONFLICT DO NOTHING",
                version,
            )


async def _seed_champions(conn: asyncpg.Connection, seed: str) -> None:
    raw = json.loads(CHAMPIONS_JSON.read_text(encoding="utf-8"))
    inserted = 0
    updated = 0
    for entry in raw:
        name: str = entry["name"]
        tier: int = entry["tier"]
        region = entry.get("region")
        factions = entry.get("factions") or []
        damage_type = entry["damage_type"]
        splash_url = entry.get("splash_url")

        existing = await conn.fetchrow(
            "SELECT drop_weight FROM champions WHERE name = $1", name
        )
        if existing is None:
            weight = assign_drop_weight(name, tier, seed)
            await conn.execute(
                """
                INSERT INTO champions (name, tier, region, factions, damage_type, drop_weight, splash_url)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                name, tier, region, factions, damage_type, weight, splash_url,
            )
            inserted += 1
        else:
            await conn.execute(
                """
                UPDATE champions
                   SET tier = $2,
                       region = $3,
                       factions = $4,
                       damage_type = $5,
                       splash_url = $6
                 WHERE name = $1
                """,
                name, tier, region, factions, damage_type, splash_url,
            )
            updated += 1

    log.info("Champion seed complete: %d inserted, %d updated.", inserted, updated)


async def run(drop_weight_seed: str) -> None:
    """Apply SQL migrations and idempotently seed champion data."""
    p = pool.get_pool()
    async with p.acquire() as conn:
        await _apply_sql_migrations(conn)
        await _seed_champions(conn, drop_weight_seed)


async def _cli() -> None:
    settings = Settings.load()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    await pool.init_pool(settings.database_url)
    try:
        await run(settings.drop_weight_seed)
    finally:
        await pool.close_pool()


if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    asyncio.run(_cli())
