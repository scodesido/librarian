------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

-- Per-user worker-event ledger. The three background workers
-- (blob_extractor, node_extractor, tree_builder) run detached from any
-- request, so when one can't make progress for a user — a missing token,
-- an expired key, a provider rate limit on that user's account — the only
-- prior trace was an operator-side log line. This table is the workers'
-- channel for telling a specific user what happened on their behalf:
-- failures (so they know why the pipeline stalled) plus a couple of coarse
-- success milestones (so they know when it's done).
--
-- See docs/15.user_worker_events.md for the architecture (the four code
-- bands, off-transaction failure recording, write throttling).
--
-- Append-only, same as user_token_usage and the immutable data tables:
-- prevent_any_update keeps history intact, which is what lets a future
-- notification feed reuse the ledger.
--
-- `code` carries the event reason; its thousands digit is the category
-- (1xxx informational, 2xxx internal error, 3xxx external provider error,
-- 4xxx user-actionable config error). The CHECK pins only the BAND as a
-- range, deliberately NOT an IN-list: the EventCode IntEnum in
-- db/tables/user_worker_events.py is the source of truth for which codes
-- within the band are live, so adding a code is an enum edit with no
-- migration. Contrast user_token_usage.operation, whose small fixed
-- vocabulary keeps an IN-list CHECK.
--
-- `source` (which worker emitted the event) does keep an IN-list CHECK —
-- a small, stable vocabulary; adding a worker is a Pydantic + migration
-- pair, same shape as data_files.source.
--
-- `context` is optional structured JSONB (e.g. {slot, provider, file_id,
-- node_id, http_status}); JSONB rather than columns for the same
-- "grow without a migration" reason as user_settings.models.
CREATE TABLE user_worker_events (
    event_id    BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code        INT NOT NULL CHECK (code BETWEEN 1000 AND 4999),
    source      TEXT NOT NULL CHECK (source IN (
                    'blob_extractor',
                    'node_extractor',
                    'tree_builder'
                )),
    detail      TEXT,
    context     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Serves both reads — "this user's most recent events" (the API) and the
-- write throttle's "is there an identical recent row?" pre-write lookup.
CREATE INDEX idx_user_worker_events_user_id_created_at
    ON user_worker_events (user_id, created_at DESC);

CREATE TRIGGER user_worker_events_prevent_any_update
    BEFORE UPDATE ON user_worker_events
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP TABLE IF EXISTS user_worker_events;
