-- World bosses: server-shared community fights spawned ~1-2x per week.
-- Multi-strike, time-windowed, top-3 split loot.

BEGIN;

CREATE TABLE IF NOT EXISTS world_bosses (
    id           BIGSERIAL PRIMARY KEY,
    boss_key     TEXT NOT NULL,
    channel_id   BIGINT NOT NULL,
    hp_total     BIGINT NOT NULL,
    hp_remaining BIGINT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','defeated','expired')),
    spawned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL,
    resolved_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_world_bosses_active
    ON world_bosses (boss_key, status)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS world_boss_damage (
    boss_id        BIGINT NOT NULL REFERENCES world_bosses(id) ON DELETE CASCADE,
    user_id        BIGINT NOT NULL REFERENCES users(discord_id),
    damage_dealt   BIGINT NOT NULL DEFAULT 0,
    last_strike_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (boss_id, user_id)
);

CREATE TABLE IF NOT EXISTS server_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

COMMIT;
