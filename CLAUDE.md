# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Discord gambling/gacha bot where players roll League of Legends champions by lore-based rarity (Common → Death, 7 tiers), equip them to a loadout, grind a fast PVE jungle loop, fight other players, trade, and prestige. Single-server bot, deployed on Fly.io. The full game design is in `PRD.md` — read it before changing game mechanics; it is the source of truth for balance decisions and locked design choices.

## Commands

```bash
# Setup (Python 3.11+; the live deploy runs 3.12)
python -m venv .venv && .venv\Scripts\Activate.ps1   # Windows
pip install -e ".[dev]"

# Local Postgres
docker run -d --name lolrng-pg -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=lolrng -p 5432:5432 postgres:16

# Apply migrations + seed the 172-champion roster (idempotent — safe to re-run)
python -m bot.db.migrate

# Run the bot
python -m bot.main

# Tests
python -m pytest tests/ -q
python -m pytest tests/test_combat.py -q                       # single file
python -m pytest tests/test_combat.py::test_power_scales_with_tier -q   # single test

# Lint
ruff check bot/ tests/

# Deploy (Fly CLI must be authenticated)
fly deploy
fly logs --no-tail        # inspect; grep for ERROR/Traceback to debug
```

There is no separate build step — it's a pure-Python app. The `Dockerfile` just `pip install`s and runs `python -m bot.main`.

## Architecture

### Layering (strict — respect it)

The codebase separates **pure game logic** from **Discord I/O**:

- **`bot/game/`** — pure functions and dataclasses. No `discord` imports, no DB writes in the leaf modules. This is where balance math lives and where ~all unit tests point. `combat.py`, `economy.py`, `leveling.py`, `rolling.py`, `seed_weights.py` are fully pure. `pvp_flow.py` and the `actions/runner.py` + `pve/runner.py` orchestrators *do* touch the DB but contain no Discord code.
- **`bot/cogs/`** — Discord slash-command handlers. Thin: parse the interaction, call into `bot/game/` and `bot/db/`, render an embed. Business logic does NOT belong here.
- **`bot/db/queries.py`** — the entire data-access layer. Every SQL statement in the project lives here. Cogs and game logic call these async helpers; they never write raw SQL.
- **`bot/utils/`** — `embeds.py` (all embed builders), `decorators.py` (`@register_user`), `champion_images.py` (CDN URL helper).
- **`bot/tasks/`** — `discord.ext.tasks` background loops (trade expiry, reap expiry, world boss scheduler, ambient event spawner).

When adding a feature: pure rules → `bot/game/`, persistence → a new function in `queries.py`, the command → a cog. Don't shortcut by putting SQL or game math in a cog.

### Entry point

`bot/main.py` — `LolRngBot.setup_hook()` initializes the asyncpg pool, runs migrations, loads every cog in the `COGS` tuple, syncs slash commands to the configured guild, and starts the background tasks. To add a cog you must append it to `COGS`. New background-task loops must be `.start()`-ed here and `.cancel()`-ed in `close()`.

### Database access pattern

`bot/db/pool.py` holds a module-global asyncpg pool. **`statement_cache_size=0` is set deliberately** — Supabase's pgbouncer pooler rotates backend connections and invalidates cached prepared statements; do not remove it.

`queries.py` convention: single-statement helpers acquire from the pool themselves; multi-statement / atomic operations (trade accept, pull resolution, action payout) accept an optional `conn: asyncpg.Connection` so the caller owns the transaction. When a sequence of writes must be atomic, open `async with pool.acquire() as conn: async with conn.transaction():` and thread `conn=conn` through.

### Cooldowns are a key-value store

The `cooldowns` table (`user_id`, `action_key`, `available_at`) backs far more than action cooldowns. By convention, `action_key` values starting with `_` are internal, non-command cooldowns:
- `_champ:<champion_id>` — champion respawn timer (a champion is "dead" / unusable while this is active)
- `_soul:<type>` — active 1-hour dragon soul buff
- `_strike:<boss_id>` — per-user world-boss strike cooldown
- `_world_ender_active`, `_lambs_respite`, `_hunt:<target_id>` — God/Death action effects

`get_all_cooldowns()` returns everything; filter by key prefix. This is why there's no separate "buffs" or "respawns" table.

### Champion death + `alive_loadout`

Failed PVE fights kill the lead champion (a `_champ:<id>` cooldown). **Every code path that picks a champion must call `queries.alive_loadout()` instead of `get_loadout()`** so dead champions are excluded — this includes `actions/runner.py`, `pvp_flow.py`, the PVE runner, ambient handler, and `/menu` eligibility checks. Forgetting this is a recurring bug source.

### The action system

Actions (`/work`, `/forage`, `/raid-noxus`, etc.) are data, not code. `bot/game/actions/registry.py` defines an `ActionSpec` per action (cooldown, champion requirements, payouts, drop table). `bot/game/actions/runner.py::run_action()` is the single executor: it enforces level gates, loadout requirements, cooldowns, synergy bonuses, drops, and persists everything in one transaction. `check_eligibility()` is a side-effect-free dry-run used by `/menu`. Adding an action = add an `ActionSpec` + register the slash command in a cog; the runner handles the rest. God/Death actions (`bot/cogs/godlike.py`) gate through `run_action` for the cooldown/requirement check, then layer their unique side-effects.

### The PVE system (`bot/game/pve/`)

`/hunt-camp` is a **random** encounter — `camps.py::roll_encounter()` weight-samples from `ENCOUNTER_POOL`. The player sees an engage/back-out View; the cooldown is set the moment the encounter posts (this is the anti-spam mechanism — do not move it to the button callbacks). `combat.py` has the punishing tier-difference win curve (`PVE_WIN_PCT_BY_DIFF`). `souls.py` implements the six 1-hour dragon soul buffs (auto-activate on drop). `world_bosses.py` + `bot/tasks/world_boss_scheduler.py` handle the rare community bosses. `encounters.py` is the regional `/explore` content.

### Combat reuse

PVE and PvP both build on `bot/game/combat.py` (`power_score`, `champion_stats`) but use different win models: PvP uses a multi-round best-of-3 skirmish with a ±25%-capped tier modifier; PVE uses the steep `PVE_WIN_PCT_BY_DIFF` lookup table. Don't conflate them.

## Conventions

- **Migrations** are raw SQL files in `migrations/`, applied in filename order by `bot/db/migrate.py`, tracked in the `schema_migrations` table. They must be idempotent (`IF NOT EXISTS`, etc.). Numbering currently jumps (`0001`, `0002`, `0004`, `0005`, `0006`) — that's fine; the runner applies whatever is present and unapplied. Champion seeding from `data/champions.json` also runs every startup as an idempotent upsert (`drop_weight` is assigned once on first insert and never overwritten).
- **Champion images**: don't store per-image URLs in code. `data/champions.json` carries the full `splash_url`; `bot/utils/champion_images.py` derives tile/icon URLs from the champion name (with a `_SPECIAL` map for Riot's quirky IDs like Wukong → MonkeyKing). All art comes from Community Dragon's CDN.
- **Embeds**: build them in `bot/utils/embeds.py`, not inline in cogs. Multi-image displays use *stacked embeds* (multiple embeds in one message via `send_message(embeds=[...])`) — e.g. PvP returns 3 embeds, the loadout dashboard returns header + one per slot. No Pillow / server-side compositing.
- **Discord button emojis** must be true emoji-presentation characters. Plain glyphs like `←`/`→` (U+2190/2192) are rejected with `400 Invalid Form Body` — use `⬅️`/`➡️`, and add the U+FE0F variation selector where needed (`🛠️` not `🛠`).
- **`@register_user`** decorator (from `bot/utils/decorators.py`) must wrap every game slash command — it ensures the user row exists and grants the starter Roll Token on first use.
- Game-state-affecting commands post **public** embeds; personal info (`/menu`, `/inventory`, `/profile`, `/loadout`) is `ephemeral=True`.

## Environment / deploy

`.env` (gitignored; copy from `.env.example`) needs `DISCORD_TOKEN`, `DISCORD_GUILD_ID`, `DATABASE_URL`, optionally `LOG_LEVEL` and `DROP_WEIGHT_SEED`. `bot/config.py::Settings.load()` reads them. The database is Supabase Postgres (use the **pooler** connection string, port 6543). Hosting is Fly.io (`fly.toml` — a worker process, no HTTP service). Slash commands are guild-scoped for instant sync.

## Testing

Tests cover the pure `bot/game/` modules only (combat, economy, leveling, rolling, PVE combat/pool, economy curve) — there are no integration tests against a live DB. When changing balance math or adding game-logic functions, add/extend a `tests/test_*.py`. Cog code is verified manually in Discord + by reading `fly logs`.
