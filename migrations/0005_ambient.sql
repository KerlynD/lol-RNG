-- Ambient events: bot pings random opted-in players with surprise encounters.

BEGIN;

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS ambient_events_opt_in BOOL NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS ambient_events (
    id            BIGSERIAL PRIMARY KEY,
    target_id     BIGINT NOT NULL REFERENCES users(discord_id),
    channel_id    BIGINT NOT NULL,
    message_id    BIGINT,
    event_type    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending','won','lost','fled','expired')),
    spawned_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at    TIMESTAMPTZ NOT NULL,
    resolved_at   TIMESTAMPTZ,
    outcome_gold  BIGINT,
    outcome_xp    INT
);

CREATE INDEX IF NOT EXISTS idx_ambient_active
    ON ambient_events (target_id, status)
    WHERE status = 'pending';

COMMIT;
