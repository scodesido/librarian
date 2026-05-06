------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

------------------------------------------------------------------------------
-- Trigger functions ---------------------------------------------------------
------------------------------------------------------------------------------
CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION prevent_created_at_change() RETURNS trigger AS $$
BEGIN
    IF NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'created_at is immutable';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

------------------------------------------------------------------------------
-- User table ----------------------------------------------------------------
------------------------------------------------------------------------------
CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    user_name   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER users_prevent_created_at_change
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Session table -------------------------------------------------------------
------------------------------------------------------------------------------
CREATE TABLE auth_sessions (
    id          TEXT PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX idx_auth_sessions_expires_at ON auth_sessions(expires_at);

CREATE TRIGGER auth_sessions_prevent_created_at_change
    BEFORE UPDATE ON auth_sessions
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Google auth table ---------------------------------------------------------
------------------------------------------------------------------------------
CREATE TABLE auth_google (
    user_id            BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    sub                TEXT NOT NULL UNIQUE,
    email              TEXT NOT NULL,
    refresh_token_enc  BYTEA NOT NULL,
    scopes             TEXT[] NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_auth_google_email ON auth_google(email);

CREATE TRIGGER auth_google_set_updated_at
    BEFORE UPDATE ON auth_google
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER auth_google_prevent_created_at_change
    BEFORE UPDATE ON auth_google
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP TABLE IF EXISTS auth_sessions;
DROP TABLE IF EXISTS auth_google;
DROP TABLE IF EXISTS users;

DROP FUNCTION IF EXISTS prevent_created_at_change();
DROP FUNCTION IF EXISTS set_updated_at();
