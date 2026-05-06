-- migrate:up

CREATE TABLE auth_google_refresh_tokens (
    user_name            TEXT PRIMARY KEY,
    refresh_token_enc    BYTEA NOT NULL,
    scopes               TEXT[] NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE auth_sessions (
    id           TEXT PRIMARY KEY,
    user_name    TEXT NOT NULL REFERENCES auth_google_refresh_tokens(user_name) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_auth_sessions_user_name ON auth_sessions(user_name);
CREATE INDEX idx_auth_sessions_expires_at ON auth_sessions(expires_at);

-- migrate:down

DROP TABLE IF EXISTS auth_sessions;
DROP TABLE IF EXISTS auth_google_refresh_tokens;
