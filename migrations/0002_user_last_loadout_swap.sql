-- Add a last_loadout_swap column on users to enforce the 30-min swap
-- cooldown from PRD §4. NULL means "no recent swap" (allowed immediately).

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS last_loadout_swap TIMESTAMPTZ;
