-- v3 Runeterra Adventure — Phase 1 foundation.
-- A player now has a *location* in the world and a set of unlocked regions.
-- Game commands are gated behind /start-adventure (adventure_started_at).

BEGIN;

-- Location + onboarding state on the user row.
ALTER TABLE users ADD COLUMN IF NOT EXISTS current_region TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS adventure_started_at TIMESTAMPTZ;

-- Which regions a player has unlocked (always at least their starting region).
CREATE TABLE IF NOT EXISTS user_regions (
    user_id     BIGINT NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    region_key  TEXT NOT NULL,
    unlocked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, region_key)
);

-- Counter-style goal progress (kills, hunts, quests completed). Threshold
-- goals (gold/level) are computed live from the users row, not stored here.
CREATE TABLE IF NOT EXISTS user_goal_progress (
    user_id   BIGINT NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    goal_key  TEXT NOT NULL,
    progress  INT NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, goal_key)
);

-- Region quests a player has picked up (Phase 4 wires the content).
CREATE TABLE IF NOT EXISTS user_quests (
    user_id      BIGINT NOT NULL REFERENCES users(discord_id) ON DELETE CASCADE,
    quest_key    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active', 'completed')),
    accepted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (user_id, quest_key)
);

COMMIT;
