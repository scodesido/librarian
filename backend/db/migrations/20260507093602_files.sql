-- migrate:up

------------------------------------------------------------------------------
-- Data files ----------------------------------------------------------------
------------------------------------------------------------------------------
CREATE TABLE data_files (
    file_id     BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    source      TEXT NOT NULL CHECK (source IN ('GDRIVE')),
    type        TEXT NOT NULL CHECK (type IN ('PDF', 'TEXT', 'OTHER')),
    state       TEXT NOT NULL CHECK (state IN ('PENDING', 'READY')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, source, path)
);

CREATE INDEX idx_data_files_user_state ON data_files(user_id, state);

CREATE TRIGGER data_files_set_updated_at
    BEFORE UPDATE ON data_files
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER data_files_prevent_created_at_change
    BEFORE UPDATE ON data_files
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Data blobs ----------------------------------------------------------------
------------------------------------------------------------------------------
-- "start" and "end" are quoted because "end" is a reserved word in
-- PostgreSQL; quoting both keeps the pair visually consistent.
CREATE TABLE data_blobs (
    blob_id     BIGSERIAL PRIMARY KEY,
    file_id     BIGINT NOT NULL REFERENCES data_files(file_id) ON DELETE CASCADE,
    "start"     INT NOT NULL,
    "end"       INT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_data_blobs_file_id ON data_blobs(file_id);

CREATE TRIGGER data_blobs_set_updated_at
    BEFORE UPDATE ON data_blobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER data_blobs_prevent_created_at_change
    BEFORE UPDATE ON data_blobs
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


-- migrate:down

DROP TABLE IF EXISTS data_blobs;
DROP TABLE IF EXISTS data_files;
