-- 0009: Champion levels — per-owned-champion progression.
-- Each owned champion gains XP, levels 1->18, and banks ability points spent
-- on Q/W/E/R ranks. State is 1:1 with a user_champions row, so it lives here.
-- The 'revive_potion' item rides the existing inventory table — no schema change.

BEGIN;

ALTER TABLE user_champions
    ADD COLUMN IF NOT EXISTS champ_level    INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS champ_xp       INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS q_rank         INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS w_rank         INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS e_rank         INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS r_rank         INTEGER NOT NULL DEFAULT 0,
    -- Fresh champs start with 1 point so 1 + 17 level-ups = exactly 18.
    ADD COLUMN IF NOT EXISTS unspent_points INTEGER NOT NULL DEFAULT 1;

COMMIT;
