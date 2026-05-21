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
- [x] Rolling (multiplier rolls 1x / 10x / 100x / 1000x, fragment redemption)
- [x] Loadout + leveling (3 → 5 slots, 30-min swap cooldown, synergies)
- [x] Tier 1–7 actions (28 commands across all 7 tiers)
- [x] PvP combat (best-of-3 multi-round skirmish, typed shields, 3/24h cap)
- [x] Trading (1h expiry, flat 500 gold tax, locked champions)
- [x] Prestige (Lv30 reset, +5% gold, Death-tier rate boost)
- [x] **v2 PVE:** random `/hunt-camp` with engage/back-out, champion death (5–15 min respawns), punishing tier-diff curve, red_buff / blue_buff consumables, dragon souls
- [x] **v2 World bosses:** Baron / Herald / Atakhan / Elder spawn 1–2x per week, 1–2h windows, multi-strike, top-3 split rewards
- [x] **v2 Ambient encounters:** opt-in surprise pings (~20–40 min) with persistent Fight/Run buttons
- [x] **v2 Regional exploration:** `/explore` 11 regions, 33 hand-authored vignettes, lore collection

## Commands at a glance

- **Discovery:** `/menu` — personalized "what can I do right now" dashboard (now shows PVE camps, dead champs, world boss, ambient state, regional availability)
- **Core:** `/profile` `/inventory` `/champions` `/shields` `/loadout` `/equip` `/unequip` `/lock` `/unlock`
- **Rolling:** `/roll` `/roll10` `/roll100` `/roll1000` `/redeem-fragment`
- **Daily-loop:** `/daily` `/work` `/beg`
- **PVE:** `/hunt-camp` (random encounter) · `/explore region:<choice>` · `/lore`
- **World boss:** `/worldboss` `/strike`
- **Ambient:** `/ambient-toggle` `/settings`
- **Yordle/region actions:** `/forage` `/tinker` `/patrol-demacia` `/meditate-ionia` `/hunt-shadowisles`
- **PvP:** `/attack` `/duel` `/prank` `/raid-noxus` `/heist-piltover`
- **Faction actions:** `/ascend` `/darkin-pact` `/defend-targon` `/void-touch`
- **Legendary actions:** `/void-incursion` `/celestial-gaze` `/freljord-storm` `/judgment`
- **God actions:** `/reshape-stars` `/world-ender` `/wander` `/portal`
- **Death (Kindred):** `/reap` `/lambs-respite` `/eternal-hunt` `/spy` `/never-one-without-the-other`
- **Trading:** `/trade` `/accept` `/decline` `/cancel` `/trades` `/trade-log`
- **Admin:** `/admin-set-boss-channel` `/admin-set-ambient-channel` `/admin-spawn-boss`
- **Endgame:** `/prestige`
