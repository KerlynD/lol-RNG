-- lol-RNG initial schema (v0)
-- Covers: users, champions, ownership, loadouts, inventory, cooldowns,
-- PvP log, trades, reap marks, and migration tracking.

BEGIN;

-- ----------------------------------------------------------------------------
-- schema_migrations: tracks which migration files have been applied
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- users: per-player state
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    discord_id            BIGINT PRIMARY KEY,
    gold                  BIGINT NOT NULL DEFAULT 0 CHECK (gold >= 0),
    xp                    INT    NOT NULL DEFAULT 0 CHECK (xp >= 0),
    level                 INT    NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 30),
    prestige              INT    NOT NULL DEFAULT 0 CHECK (prestige >= 0),
    starter_token_granted BOOL   NOT NULL DEFAULT FALSE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- champions: roster, seeded from data/champions.json on bot startup
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS champions (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    tier        SMALLINT NOT NULL CHECK (tier BETWEEN 1 AND 7),
    region      TEXT,
    factions    TEXT[] NOT NULL DEFAULT '{}',
    damage_type TEXT NOT NULL CHECK (damage_type IN ('AD','AP','Hybrid')),
    drop_weight DOUBLE PRECISION NOT NULL CHECK (drop_weight > 0),
    splash_url  TEXT
);

CREATE INDEX IF NOT EXISTS idx_champions_tier ON champions (tier);

-- ----------------------------------------------------------------------------
-- user_champions: ownership ledger (presence, not counter — dupes -> fragments)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_champions (
    user_id     BIGINT NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    champion_id INT    NOT NULL REFERENCES champions(id),
    locked      BOOL   NOT NULL DEFAULT FALSE,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, champion_id)
);

CREATE INDEX IF NOT EXISTS idx_user_champions_user ON user_champions (user_id);

-- ----------------------------------------------------------------------------
-- loadouts: equipped slots, 1 row per occupied slot
-- App layer enforces slot-count cap (3 at Lv1, 4 at Lv10, 5 at Lv20)
-- and that champion_id is owned by user_id.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loadouts (
    user_id     BIGINT NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    slot        SMALLINT NOT NULL CHECK (slot BETWEEN 1 AND 5),
    champion_id INT NOT NULL REFERENCES champions(id),
    PRIMARY KEY (user_id, slot)
);

-- ----------------------------------------------------------------------------
-- inventory: all fungible items keyed by item_type string
-- Valid types (enforced in app layer):
--   roll_token
--   shield_physical, shield_magic, aegis, stasis
--   fragment_t1 ... fragment_t6   (no fragment_t7 — Death has no fragment path)
--   mat, soul, corruption_stack
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS inventory (
    user_id   BIGINT NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    item_type TEXT   NOT NULL,
    quantity  INT    NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    PRIMARY KEY (user_id, item_type)
);

-- ----------------------------------------------------------------------------
-- cooldowns: per-action availability
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cooldowns (
    user_id       BIGINT NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    action_key    TEXT   NOT NULL,
    available_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, action_key)
);

-- ----------------------------------------------------------------------------
-- pvp_log: combat history + driver for 3-attacks-per-24h cap (PRD §5.4)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pvp_log (
    id               BIGSERIAL PRIMARY KEY,
    attacker_id      BIGINT NOT NULL REFERENCES users(discord_id),
    defender_id      BIGINT NOT NULL REFERENCES users(discord_id),
    outcome          TEXT   NOT NULL CHECK (outcome IN ('attacker_win','defender_win')),
    gold_transferred BIGINT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pvp_log_defender_recent
    ON pvp_log (defender_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- trades: pending + historical. Auto-expire after 1h via background sweep.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    id                    BIGSERIAL PRIMARY KEY,
    initiator_id          BIGINT NOT NULL REFERENCES users(discord_id),
    target_id             BIGINT NOT NULL REFERENCES users(discord_id),
    offered_champion_id   INT    NOT NULL REFERENCES champions(id),
    requested_champion_id INT    NOT NULL REFERENCES champions(id),
    status                TEXT   NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending','accepted','declined','expired','cancelled')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at            TIMESTAMPTZ NOT NULL,
    resolved_at           TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_trades_pending_expiry
    ON trades (status, expires_at)
    WHERE status = 'pending';

-- ----------------------------------------------------------------------------
-- reap_marks: Kindred /reap is exclusive — at most one mark per target.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reap_marks (
    target_id  BIGINT PRIMARY KEY REFERENCES users(discord_id) ON DELETE CASCADE,
    caster_id  BIGINT NOT NULL REFERENCES users(discord_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

COMMIT;
