# lol-RNG

Discord gambling/gacha bot — roll League of Legends champions by lore-based rarity (Common → Death), equip them, do tier-gated actions, fight other players. Design lives in [PRD.md](PRD.md).

This README covers **v0 scaffold setup only**. Game logic ships in later passes.

---

## Stack

- Python 3.11+ / discord.py 2.x (slash commands via `app_commands`)
- PostgreSQL 16 via `asyncpg`
- Hosted on Fly.io

---

## Local development

### 1. Clone + venv

```powershell
git clone <repo>
cd lol-RNG
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### 2. Start a local Postgres

```powershell
docker run -d --name lolrng-pg `
  -e POSTGRES_PASSWORD=dev `
  -e POSTGRES_DB=lolrng `
  -p 5432:5432 `
  postgres:16
```

### 3. Configure environment

```powershell
Copy-Item .env.example .env
# Edit .env: paste your DISCORD_TOKEN, DISCORD_GUILD_ID, and the DATABASE_URL above.
```

### 4. Run migrations + seed champions

```powershell
python -m bot.db.migrate
```

This applies `migrations/0001_init.sql` then upserts every champion in `data/champions.json` into the `champions` table, assigning a deterministic random drop weight per champion (seeded by `DROP_WEIGHT_SEED`).

### 5. Start the bot

```powershell
python -m bot.main
```

In your server: `/ping` should return a latency. `/dbcheck` should report the seeded champion count.

---

## Project layout

```
bot/
  main.py        entry point
  config.py      env-loaded Settings
  cogs/          slash command groups (one cog per feature)
  db/            asyncpg pool + migration runner
  game/          pure game logic, no discord.py imports
  utils/         embed builders, helpers
data/
  champions.json single source of truth for the roster
migrations/
  0001_init.sql  initial schema
```

---

## Deploying to Fly.io

You already have a Fly account. From the repo root:

```powershell
fly launch --no-deploy   # accept fly.toml, skip first deploy
fly postgres create --name lol-rng-db
fly postgres attach lol-rng-db   # sets DATABASE_URL automatically
fly secrets set DISCORD_TOKEN=... DISCORD_GUILD_ID=... DROP_WEIGHT_SEED=lol-rng-v0
fly deploy
```

The bot autoruns migrations on startup, so the first deploy seeds the DB.

---

## Status

- [x] Repo scaffold
- [x] Champion roster + schema
- [ ] Rolling (multiplier rolls)
- [ ] Loadout + leveling
- [ ] Tier 1–7 actions
- [ ] PvP combat
- [ ] Trading
- [ ] Prestige
