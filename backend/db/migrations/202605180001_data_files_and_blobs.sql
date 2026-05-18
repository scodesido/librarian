------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

CREATE EXTENSION IF NOT EXISTS vector;


------------------------------------------------------------------------------
-- Immutability trigger function ---------------------------------------------
------------------------------------------------------------------------------
-- Shared by every immutable data_* table. Once a row is written it cannot
-- be modified, only deleted. The DB-layer enforcement protects the
-- application from accidentally violating the invariant that the rest of
-- the design (cascade triggers, state-by-existence) relies on.
CREATE FUNCTION prevent_any_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'rows of this table are immutable; UPDATE is rejected';
END;
$$ LANGUAGE plpgsql;


------------------------------------------------------------------------------
-- Data files ----------------------------------------------------------------
------------------------------------------------------------------------------
-- One row per file we know about. Readiness is defined by the existence of
-- a data_blobs row with is_final_blob = TRUE for this file; there is no
-- state column.
--
-- source_modified_at is optional and only populated when the source can
-- supply it (Drive does). The sync layer uses it to detect stale files:
-- a stale row is deleted (cascading its blobs) and a fresh row inserted.
CREATE TABLE data_files (
    file_id             BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    path                TEXT NOT NULL,
    source              TEXT NOT NULL CHECK (source IN ('GDRIVE')),
    type                TEXT NOT NULL CHECK (type IN ('PDF', 'TEXT', 'OTHER')),
    source_modified_at  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, source, path)
);

CREATE TRIGGER data_files_prevent_any_update
    BEFORE UPDATE ON data_files
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();


------------------------------------------------------------------------------
-- Data blobs ----------------------------------------------------------------
------------------------------------------------------------------------------
-- Immutable. Blobs of a file form a forward-linked list ordered by
-- file_blob_index. next_blob_id points to the next blob; is_final_blob
-- marks the tail. The CHECK ties the two so the chain has exactly one tail.
--
-- file_start and file_end are a half-open range. Their unit is
-- type-dependent (0-based page numbers for PDF; 0-based character offsets
-- for TEXT). file_end > file_start always.
--
-- embedding_blob and embedding_with_file are both L2-unit vectors:
--   * embedding_blob: encodes the blob's own content (raw text + Abstract).
--   * embedding_with_file: normalize(embedding_blob + file_embedding),
--     where file_embedding is the unit-normalized sum of embedding_blob
--     across all blobs of the file. Used by tree_builder so blobs of the
--     same file tend to cluster together during insertion.
--
-- next_blob_id uses NO ACTION DEFERRABLE INITIALLY DEFERRED so a cascading
-- delete of an entire file's blob set doesn't fail on the still-existing
-- self-reference mid-statement. At commit time, all blobs of the file are
-- gone and nothing dangles. Equivalent to RESTRICT for defensive purposes
-- (a transaction that leaves a dangling pointer is rejected), but
-- compatible with cascades.
--
-- Direct deletion of any blob deletes the owning data_files row via the
-- after-delete trigger; that in turn cascades and removes every other blob
-- of the file. The reverse path is naturally bounded: once the file row is
-- gone the trigger's DELETE is a no-op.
CREATE TABLE data_blobs (
    blob_id              BIGSERIAL PRIMARY KEY,
    user_id              BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    file_id              BIGINT NOT NULL REFERENCES data_files(file_id) ON DELETE CASCADE,
    file_blob_index      INT NOT NULL CHECK (file_blob_index >= 0),
    file_start           INT NOT NULL CHECK (file_start >= 0),
    file_end             INT NOT NULL,
    is_final_blob        BOOLEAN NOT NULL,
    next_blob_id         BIGINT REFERENCES data_blobs(blob_id)
                              ON DELETE NO ACTION
                              DEFERRABLE INITIALLY DEFERRED,
    embedding_blob       vector(1024) NOT NULL,
    embedding_with_file  vector(1024) NOT NULL,
    abstract             JSONB NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (file_id, file_blob_index),
    CHECK (file_end > file_start),
    CHECK ((next_blob_id IS NULL) = is_final_blob)
);

-- Exactly one tail blob per file. Also serves as the "is this file ready?"
-- probe: EXISTS(SELECT 1 FROM data_blobs WHERE file_id = $1 AND is_final_blob)
-- becomes an index-only check.
CREATE UNIQUE INDEX data_blobs_one_final_per_file
    ON data_blobs(file_id) WHERE is_final_blob;

CREATE INDEX idx_data_blobs_user_id ON data_blobs(user_id);

CREATE TRIGGER data_blobs_prevent_any_update
    BEFORE UPDATE ON data_blobs
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();


CREATE FUNCTION data_blobs_delete_owning_file() RETURNS trigger AS $$
BEGIN
    DELETE FROM data_files WHERE file_id = OLD.file_id;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_blobs_delete_owning_file
    AFTER DELETE ON data_blobs
    FOR EACH ROW EXECUTE FUNCTION data_blobs_delete_owning_file();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP TABLE IF EXISTS data_blobs;
DROP TABLE IF EXISTS data_files;
DROP FUNCTION IF EXISTS data_blobs_delete_owning_file();
DROP FUNCTION IF EXISTS prevent_any_update();
DROP EXTENSION IF EXISTS vector;
