-- v3 trading: one interactive embed both players use, multi-item offers.
-- Adds a trade_items side-table plus per-side confirm flags and message refs
-- on the existing trades row. The legacy single-champion columns become
-- nullable; new trades won't populate them.

BEGIN;

ALTER TABLE trades
    ALTER COLUMN offered_champion_id   DROP NOT NULL,
    ALTER COLUMN requested_champion_id DROP NOT NULL;

ALTER TABLE trades
    ADD COLUMN IF NOT EXISTS initiator_confirmed BOOL NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS target_confirmed    BOOL NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS channel_id          BIGINT,
    ADD COLUMN IF NOT EXISTS message_id          BIGINT;

CREATE TABLE IF NOT EXISTS trade_items (
    id           BIGSERIAL PRIMARY KEY,
    trade_id     BIGINT NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    side         TEXT   NOT NULL CHECK (side IN ('initiator', 'target')),
    champion_id  INT    NOT NULL REFERENCES champions(id),
    added_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (trade_id, side, champion_id)
);

CREATE INDEX IF NOT EXISTS idx_trade_items_trade ON trade_items (trade_id);

COMMIT;
