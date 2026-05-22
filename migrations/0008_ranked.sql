-- 0007: Ranked PvP — LP ladder, seasons, and ranked match log.
-- One ranked_profiles row per user; season_id is bumped in place on reset.

BEGIN;

-- ----------------------------------------------------------------------------
-- seasons: the ranked ladder runs in seasons. The open season has ended_at NULL.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS seasons (
    id         SERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at   TIMESTAMPTZ
);

-- Seed season 1 on first apply.
INSERT INTO seasons (started_at)
SELECT NOW()
WHERE NOT EXISTS (SELECT 1 FROM seasons);

-- ----------------------------------------------------------------------------
-- ranked_profiles: per-player ladder state. hidden_mmr is NEVER wiped — it
-- carries across seasons to give veterans a soft head start in placements.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ranked_profiles (
    user_id               BIGINT PRIMARY KEY REFERENCES users(discord_id) ON DELETE CASCADE,
    season_id             INT    NOT NULL REFERENCES seasons(id),
    lp                    INT    NOT NULL DEFAULT 0 CHECK (lp >= 0),
    hidden_mmr            INT    NOT NULL DEFAULT 100,
    placement_games       INT    NOT NULL DEFAULT 0 CHECK (placement_games BETWEEN 0 AND 5),
    placement_wins        INT    NOT NULL DEFAULT 0 CHECK (placement_wins BETWEEN 0 AND 5),
    wins                  INT    NOT NULL DEFAULT 0 CHECK (wins >= 0),
    losses                INT    NOT NULL DEFAULT 0 CHECK (losses >= 0),
    win_streak            INT    NOT NULL DEFAULT 0 CHECK (win_streak >= 0),
    loss_streak           INT    NOT NULL DEFAULT 0 CHECK (loss_streak >= 0),
    last_ranked_attack_at TIMESTAMPTZ,
    last_decay_at         TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ranked_profiles_lp ON ranked_profiles (lp DESC);

-- ----------------------------------------------------------------------------
-- ranked_matches: history + driver for the 10-attacks-per-day attacker cap.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ranked_matches (
    id                BIGSERIAL PRIMARY KEY,
    season_id         INT    NOT NULL REFERENCES seasons(id),
    attacker_id       BIGINT NOT NULL REFERENCES users(discord_id),
    defender_id       BIGINT NOT NULL REFERENCES users(discord_id),
    attacker_won      BOOL   NOT NULL,
    attacker_lp_delta INT    NOT NULL DEFAULT 0,
    defender_lp_delta INT    NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ranked_matches_attacker_recent
    ON ranked_matches (attacker_id, created_at DESC);

COMMIT;
