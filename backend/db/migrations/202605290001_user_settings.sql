------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

-- Per-user settings, encrypted provider tokens, and a token-usage ledger.
-- These tables productionise what the operator-side YAML used to carry
-- under blob_extractor/node_extractor/query: model choices and API tokens
-- are now per-user, picked through the Settings tab, and the workers /
-- retrieval pipeline resolve them at iteration / request time.
--
-- See docs/14.user_settings.md for the architecture (model catalog,
-- token encryption, worker rotation, ledger semantics).


------------------------------------------------------------------------------
-- Non-sensitive user settings -----------------------------------------------
------------------------------------------------------------------------------
-- One row per user. `models` is a JSONB blob shaped by Pydantic's
-- UserModelSettings (six slot strings: blob_llm, node_llm_leaf,
-- node_llm_internal, retrieval_llm, extract_llm, embedding). We keep it
-- as JSONB rather than columns because settings are a flexible thing —
-- adding a field is a Pydantic change, not a migration. The validator
-- runs at the API layer (against the operator-defined model catalog) so
-- the DB constraint stays "is this valid JSON".
--
-- No default on `models`: missing row means "use catalog defaults". The
-- GET /settings/me endpoint synthesizes the defaults; only an explicit
-- PUT persists a row. This avoids inserting a row at user creation and
-- keeps "the user has not touched their settings" observable in-table.
--
-- Future fields (retrieval tuning, UI prefs, …) go as additional JSONB
-- columns on this same table — no joins needed, columns stay independent.
CREATE TABLE user_settings (
    user_id     BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    models      JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER user_settings_set_updated_at
    BEFORE UPDATE ON user_settings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER user_settings_prevent_created_at_change
    BEFORE UPDATE ON user_settings
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Encrypted per-slot provider tokens ----------------------------------------
------------------------------------------------------------------------------
-- One row per (user, slot). Slot-keyed rather than provider-keyed: a user
-- may run different providers in different slots (e.g. anthropic for
-- retrieval, voyage for embeddings) AND may want a different anthropic
-- key for blob_extract vs retrieval (cost/billing isolation). The
-- "Same as <slot>" affordance in the UI keeps the common case
-- frictionless without baking the sharing into the schema.
--
-- token_enc is the user-supplied API token encrypted with Fernet, using
-- the operator-side encryption key on `common.settings.llm_runtime`. Same
-- argument as auth_google.refresh_token_enc: a DB leak should not become
-- a credential leak.
--
-- The slot CHECK pins the closed vocabulary at the schema level (matches
-- the keys of UserModelSettings). Adding a slot is a Pydantic + migration
-- pair, same as today's data_files.source / data_files.type.
CREATE TABLE user_slot_tokens (
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    slot        TEXT NOT NULL CHECK (slot IN (
                    'blob_llm',
                    'node_llm_leaf',
                    'node_llm_internal',
                    'retrieval_llm',
                    'extract_llm',
                    'embedding'
                )),
    token_enc   BYTEA NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, slot)
);

CREATE TRIGGER user_slot_tokens_set_updated_at
    BEFORE UPDATE ON user_slot_tokens
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER user_slot_tokens_prevent_created_at_change
    BEFORE UPDATE ON user_slot_tokens
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Token-usage ledger --------------------------------------------------------
------------------------------------------------------------------------------
-- Append-only. One row per LLM / embedder call, including retries —
-- retries ARE billed, so the ledger reflects billing reality and lets us
-- audit retry storms separately from successful work. Cost estimation is
-- intentionally NOT computed here; the read endpoint aggregates raw token
-- counts and a future pricing table can derive cost.
--
-- `operation` pins the closed vocabulary at the schema level. The eight
-- values cover every existing call site:
--   - blob_extract:         blob_extractor main agent (one per blob)
--   - blob_tag:             blob_extractor tag classifier (one per blob)
--   - node_extract_leaf:    node_extractor height-0 agent
--   - node_extract_internal:node_extractor height>0 agent
--   - retrieval:            api retrieval agent (one per /data/query)
--   - extract_search_terms: api preflight term extractor
--   - embed_blob:           blob_extractor embedder
--   - embed_query:          api query-time embedder
--
-- `provider` is the prefix from "provider:model" (e.g. 'anthropic',
-- 'voyageai', 'ollama'); kept as TEXT (no CHECK) so adding a provider in
-- service/llm.py / service/embedder.py doesn't require a migration. The
-- full model string is stored verbatim in `model` so historical rows
-- survive catalog changes.
--
-- Embedding rows carry output_tokens = 0 (embedders don't produce output
-- tokens). prevent_any_update keeps the ledger truly append-only — same
-- pattern as data_blobs / data_files.
CREATE TABLE user_token_usage (
    usage_id       BIGSERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    operation      TEXT NOT NULL CHECK (operation IN (
                       'blob_extract',
                       'blob_tag',
                       'node_extract_leaf',
                       'node_extract_internal',
                       'retrieval',
                       'extract_search_terms',
                       'embed_blob',
                       'embed_query'
                   )),
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    input_tokens   INT NOT NULL CHECK (input_tokens >= 0),
    output_tokens  INT NOT NULL CHECK (output_tokens >= 0),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The dominant read pattern is "show this user's recent usage" and
-- "aggregate this user's usage over a window". Both want
-- (user_id, created_at) as a leading index.
CREATE INDEX idx_user_token_usage_user_id_created_at
    ON user_token_usage (user_id, created_at DESC);

CREATE TRIGGER user_token_usage_prevent_any_update
    BEFORE UPDATE ON user_token_usage
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP TABLE IF EXISTS user_token_usage;
DROP TABLE IF EXISTS user_slot_tokens;
DROP TABLE IF EXISTS user_settings;
