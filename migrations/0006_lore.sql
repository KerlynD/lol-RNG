-- Per-user lore collection (cosmetic, world-building flavor).

BEGIN;

CREATE TABLE IF NOT EXISTS user_lore (
    user_id     BIGINT NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    lore_key    TEXT NOT NULL,
    unlocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, lore_key)
);

COMMIT;
