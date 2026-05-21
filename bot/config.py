from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int
    database_url: str
    log_level: str
    drop_weight_seed: str

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(REPO_ROOT / ".env")

        token = os.environ.get("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")

        guild_raw = os.environ.get("DISCORD_GUILD_ID", "").strip()
        if not guild_raw:
            raise RuntimeError("DISCORD_GUILD_ID is not set.")
        try:
            guild_id = int(guild_raw)
        except ValueError as e:
            raise RuntimeError(f"DISCORD_GUILD_ID must be an integer, got {guild_raw!r}") from e

        db_url = os.environ.get("DATABASE_URL", "").strip()
        if not db_url:
            raise RuntimeError("DATABASE_URL is not set.")

        return cls(
            discord_token=token,
            discord_guild_id=guild_id,
            database_url=db_url,
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            drop_weight_seed=os.environ.get("DROP_WEIGHT_SEED", "lol-rng-v0"),
        )
