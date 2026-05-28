------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

-- Tables for the OAuth 2.1 authorization server that fronts the /mcp
-- endpoint. We are the AS; external MCP clients (claude.ai) register
-- dynamically (RFC 7591), redirect users here for consent, receive a
-- bearer token, and present it on subsequent /mcp calls.
--
-- User authentication itself is delegated to the existing Google OAuth
-- flow — these tables store only the AS-side state: registered clients,
-- in-flight authorization grants, and issued tokens.


------------------------------------------------------------------------------
-- Registered OAuth clients --------------------------------------------------
------------------------------------------------------------------------------
-- One row per MCP client that has called /register. We accept any client
-- that posts a well-formed registration; the security story rests on PKCE,
-- exact redirect_uri matching, and the user-facing consent screen rather
-- than on gating registrations.
--
-- token_endpoint_auth_method = 'none' for public clients (the MCP norm —
-- no client secret). Stored verbatim so /token can echo it back in errors
-- and so we can audit anomalies later.
CREATE TABLE oauth_clients (
    client_id                   TEXT PRIMARY KEY,
    client_name                 TEXT NOT NULL,
    redirect_uris               TEXT[] NOT NULL,
    scopes                      TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    grant_types                 TEXT[] NOT NULL
                                DEFAULT ARRAY['authorization_code', 'refresh_token']::TEXT[],
    response_types              TEXT[] NOT NULL DEFAULT ARRAY['code']::TEXT[],
    token_endpoint_auth_method  TEXT NOT NULL DEFAULT 'none',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER oauth_clients_prevent_created_at_change
    BEFORE UPDATE ON oauth_clients
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Authorization grants ------------------------------------------------------
------------------------------------------------------------------------------
-- Combined "pending consent" and "granted authorization code" state in one
-- table, distinguished by `status`:
--
--   'pending'  - SDK called provider.authorize(); we stashed the
--                AuthorizationParams keyed by `code` (nonce). user_id is
--                NULL until consent is granted.
--   'granted'  - User signed in and approved on the consent screen. user_id
--                is now set. The MCP client has been redirected to its
--                redirect_uri with this `code`. Ready to be exchanged at
--                /token.
--   'consumed' - /token has exchanged the code for tokens. Kept briefly
--                for auditability; expires_at still applies.
--
-- A single table keeps the flow self-contained (one row tracks the whole
-- "client requested auth → user consented → code redeemed" arc) and avoids
-- the two-table sync hazard.
CREATE TABLE oauth_authorization_grants (
    code                    TEXT PRIMARY KEY,
    client_id               TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
    user_id                 BIGINT REFERENCES users(id) ON DELETE CASCADE,
    redirect_uri            TEXT NOT NULL,
    redirect_uri_explicit   BOOLEAN NOT NULL,
    code_challenge          TEXT NOT NULL,
    requested_scopes        TEXT[] NOT NULL,
    resource                TEXT,
    client_state            TEXT,
    status                  TEXT NOT NULL,
    expires_at              TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT oauth_authorization_grants_status_check
        CHECK (status IN ('pending', 'granted', 'consumed')),
    -- A granted/consumed grant must have a user attached. A pending grant
    -- must not (consent is what attaches it).
    CONSTRAINT oauth_authorization_grants_user_id_status_check
        CHECK ((status = 'pending') = (user_id IS NULL))
);

CREATE INDEX idx_oauth_authorization_grants_expires_at
    ON oauth_authorization_grants(expires_at);

CREATE TRIGGER oauth_authorization_grants_set_updated_at
    BEFORE UPDATE ON oauth_authorization_grants
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER oauth_authorization_grants_prevent_created_at_change
    BEFORE UPDATE ON oauth_authorization_grants
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Access tokens -------------------------------------------------------------
------------------------------------------------------------------------------
-- One row per issued access token. Tokens are opaque (32+ bytes of
-- entropy from `secrets.token_urlsafe`) and stored hashed at rest, same
-- argument as the Google refresh tokens being encrypted: a database leak
-- should not be a token leak. The wire-format token is shown only at
-- issue time; lookups always go through the hash.
CREATE TABLE oauth_access_tokens (
    token_hash      BYTEA PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id       TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL,
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_oauth_access_tokens_user_id ON oauth_access_tokens(user_id);
CREATE INDEX idx_oauth_access_tokens_expires_at ON oauth_access_tokens(expires_at);

CREATE TRIGGER oauth_access_tokens_prevent_created_at_change
    BEFORE UPDATE ON oauth_access_tokens
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Refresh tokens ------------------------------------------------------------
------------------------------------------------------------------------------
-- Same shape and storage policy as access tokens, separate table so the
-- two lifetimes (and any future per-type maintenance) stay independent.
CREATE TABLE oauth_refresh_tokens (
    token_hash      BYTEA PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    client_id       TEXT NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
    scopes          TEXT[] NOT NULL,
    resource        TEXT,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_oauth_refresh_tokens_user_id ON oauth_refresh_tokens(user_id);
CREATE INDEX idx_oauth_refresh_tokens_expires_at ON oauth_refresh_tokens(expires_at);

CREATE TRIGGER oauth_refresh_tokens_prevent_created_at_change
    BEFORE UPDATE ON oauth_refresh_tokens
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP TABLE IF EXISTS oauth_refresh_tokens;
DROP TABLE IF EXISTS oauth_access_tokens;
DROP TABLE IF EXISTS oauth_authorization_grants;
DROP TABLE IF EXISTS oauth_clients;
