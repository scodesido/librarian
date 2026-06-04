------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

-- Per-blob processing (see docs/19.per_blob_processing.md).
--
-- The blob_extractor used to build a file's entire blob set inside one long
-- transaction and insert it atomically. This migration splits that into an
-- incrementally-built, crash-resumable shape:
--
--   data_files            the root (unchanged)
--     -> data_file_manifests        NEW, 1:1: how many blobs the file SHOULD
--                                    have, plus parse-time metadata. Created
--                                    first, before any blob.
--          -> data_blobs            core per-blob content (abstract +
--                                    embedding_blob), now built one blob at a
--                                    time. is_final_blob/next_blob_id removed;
--                                    completeness is derived from the manifest.
--               -> data_blob_file_embeddings   NEW, 1:1: the file-relative
--                                    embedding (embedding_with_file), computed
--                                    once the whole blob set exists and
--                                    inserted as a single atomic batch.
--
-- The integrity goal: no sequence of writes the application code could
-- perform (now or in the future) can leave a file *looking* ready when it
-- isn't. That guarantee is carried by the triggers below, not by careful
-- code. See the doc for the full argument.
--
-- This migration is destructive: it cannot preserve existing blobs (the
-- embedding_with_file column moves out, is_final_blob is gone), so it clears
-- data_files to a fresh slate. Re-sync from Drive repopulates under the new
-- schema.


------------------------------------------------------------------------------
-- Drop the old blob-set integrity backstop ----------------------------------
------------------------------------------------------------------------------
-- "delete any blob -> delete the owning file" defended the linked-list /
-- single-tail invariant of the all-at-once design. Incremental construction
-- makes a partial blob set a *normal* state, so that premise is gone, and the
-- new invalidation path is "delete the manifest, blobs cascade" (file kept).
-- Drop it before the clearing wipe below so the cascade doesn't fire it.
DROP TRIGGER IF EXISTS data_blobs_delete_owning_file ON data_blobs;
DROP FUNCTION IF EXISTS data_blobs_delete_owning_file();

-- Fresh slate (see note above): clear everything so the new constraints apply
-- to a clean blob layer. Cascades data_files -> data_blobs -> data_blob_edges
-- and collapses the tree via the orphan trigger.
DELETE FROM data_files;


------------------------------------------------------------------------------
-- Data file manifests -------------------------------------------------------
------------------------------------------------------------------------------
-- One row per file, written by blob_extractor as the FIRST step of processing
-- (after downloading + chunking the file, before any blob lands). It records
-- the authoritative number of blobs the file must produce plus the metadata
-- that only becomes knowable once the bytes are in hand. Immutable: a content
-- change means deleting the manifest (cascading the blobs) and re-creating it.
--
-- expected_blob_count is the denominator the rest of the design was missing:
-- it turns "is this file complete?" from a forgeable marker into a fact the
-- triggers below can enforce absolutely.
CREATE TABLE data_file_manifests (
    file_id              BIGINT PRIMARY KEY REFERENCES data_files(file_id) ON DELETE CASCADE,
    user_id              BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expected_blob_count  INT NOT NULL CHECK (expected_blob_count >= 1),
    -- Parse-time metadata. Unit is type-dependent: page_count for PDF,
    -- char_count for TEXT (the other is left NULL). byte_size and content_hash
    -- support change-detection and future re-processing; only
    -- expected_blob_count is load-bearing today.
    page_count           INT CHECK (page_count IS NULL OR page_count >= 0),
    char_count           INT CHECK (char_count IS NULL OR char_count >= 0),
    byte_size            BIGINT CHECK (byte_size IS NULL OR byte_size >= 0),
    content_hash         TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_data_file_manifests_user ON data_file_manifests(user_id);

CREATE TRIGGER data_file_manifests_prevent_any_update
    BEFORE UPDATE ON data_file_manifests
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();

-- user_id must match the owning data_files row. Belt-and-suspenders against
-- an accidentally cross-user write (mirrors data_node_weights_check_user_id).
CREATE FUNCTION data_file_manifests_check_user_id() RETURNS trigger AS $$
DECLARE
    file_user_id BIGINT;
BEGIN
    SELECT user_id INTO file_user_id FROM data_files WHERE file_id = NEW.file_id;
    IF file_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_file_manifests user_id mismatch with data_files';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_file_manifests_check_user_id
    BEFORE INSERT ON data_file_manifests
    FOR EACH ROW EXECUTE FUNCTION data_file_manifests_check_user_id();


------------------------------------------------------------------------------
-- data_blobs: drop the all-at-once machinery, re-anchor on the manifest -----
------------------------------------------------------------------------------
-- is_final_blob + next_blob_id existed to keep the reverse-inserted linked
-- list well-formed; they're write-only and block forward (incremental)
-- insertion, so they go. embedding_with_file moves to its own 1:1 table.
DROP INDEX IF EXISTS data_blobs_one_final_per_file;

ALTER TABLE data_blobs
    DROP COLUMN next_blob_id CASCADE,        -- drops the self-FK and the chain CHECK
    DROP COLUMN is_final_blob CASCADE,       -- drops the (next_blob_id IS NULL) = is_final CHECK
    DROP COLUMN embedding_with_file;

-- Re-point the file FK from data_files to data_file_manifests: a blob now
-- literally cannot exist without its manifest. Deleting the manifest cascades
-- the blobs; deleting the file cascades file -> manifest -> blobs.
ALTER TABLE data_blobs
    DROP CONSTRAINT data_blobs_file_id_fkey,
    ADD CONSTRAINT data_blobs_file_id_fkey
        FOREIGN KEY (file_id) REFERENCES data_file_manifests(file_id) ON DELETE CASCADE;

-- BEFORE INSERT: a blob's manifest must exist, its user_id must match, and its
-- index must fall in [0, expected_blob_count). One manifest lookup covers all
-- three. This is the immediate, cheap guard; the contiguity check below is the
-- commit-time net.
CREATE FUNCTION data_blobs_check_against_manifest() RETURNS trigger AS $$
DECLARE
    m_user_id BIGINT;
    m_expected INT;
BEGIN
    SELECT user_id, expected_blob_count INTO m_user_id, m_expected
    FROM data_file_manifests WHERE file_id = NEW.file_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'data_blobs insert for file % has no manifest', NEW.file_id;
    END IF;
    IF m_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_blobs user_id mismatch with data_file_manifests';
    END IF;
    IF NEW.file_blob_index < 0 OR NEW.file_blob_index >= m_expected THEN
        RAISE EXCEPTION 'data_blobs file_blob_index % out of range [0, %) for file %',
            NEW.file_blob_index, m_expected, NEW.file_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_blobs_check_against_manifest
    BEFORE INSERT ON data_blobs
    FOR EACH ROW EXECUTE FUNCTION data_blobs_check_against_manifest();

-- DEFERRED constraint trigger: at commit, every touched file's blob indices
-- must form a contiguous 0..k prefix (or be empty). This is what makes the
-- "blob at index expected-1 exists" completeness probe trustworthy: no hole
-- can sit beneath the top index.
--
-- It MUST be deferred, not row-level: during a cascade delete the sibling rows
-- vanish in arbitrary order, so a row-level guard would misfire mid-statement.
-- Evaluating the end state once per transaction sidesteps that entirely.
-- Incremental growth always satisfies it (each insert keeps the prefix
-- contiguous); the only state it rejects is a hole punched by an out-of-band
-- delete of a non-top blob.
CREATE FUNCTION data_blobs_check_contiguous() RETURNS trigger AS $$
DECLARE
    target_file_id BIGINT;
    n INT;
    mn INT;
    mx INT;
BEGIN
    target_file_id := COALESCE(NEW.file_id, OLD.file_id);
    SELECT count(*), min(file_blob_index), max(file_blob_index)
    INTO n, mn, mx
    FROM data_blobs WHERE file_id = target_file_id;
    IF n > 0 AND (mn <> 0 OR mx <> n - 1) THEN
        RAISE EXCEPTION
            'data_blobs for file % are not a contiguous 0..k prefix (count=%, min=%, max=%)',
            target_file_id, n, mn, mx;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER data_blobs_check_contiguous
    AFTER INSERT OR DELETE ON data_blobs
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION data_blobs_check_contiguous();


------------------------------------------------------------------------------
-- Data blob file embeddings -------------------------------------------------
------------------------------------------------------------------------------
-- 1:1 with data_blobs (PK = blob_id). Holds embedding_with_file, the
-- file-relative vector tree_builder uses to bias descent so a file's blobs
-- cluster together. Derived purely (numpy, no network) from every
-- embedding_blob of the file, so it can only be computed once the whole blob
-- set exists, and the worker inserts the whole batch in one transaction.
--
-- file_id is denormalized (with FK + consistency trigger) so the all-or-none
-- check and the readiness probe are direct indexed lookups, not joins through
-- data_blobs.
CREATE TABLE data_blob_file_embeddings (
    blob_id              BIGINT PRIMARY KEY REFERENCES data_blobs(blob_id) ON DELETE CASCADE,
    file_id              BIGINT NOT NULL REFERENCES data_file_manifests(file_id) ON DELETE CASCADE,
    user_id              BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    embedding_with_file  vector(1024) NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_data_blob_file_embeddings_file ON data_blob_file_embeddings(file_id);
CREATE INDEX idx_data_blob_file_embeddings_user ON data_blob_file_embeddings(user_id);

CREATE TRIGGER data_blob_file_embeddings_prevent_any_update
    BEFORE UPDATE ON data_blob_file_embeddings
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();

-- file_id and user_id must match the parent blob's.
CREATE FUNCTION data_blob_file_embeddings_check_consistency() RETURNS trigger AS $$
DECLARE
    b_file_id BIGINT;
    b_user_id BIGINT;
BEGIN
    SELECT file_id, user_id INTO b_file_id, b_user_id
    FROM data_blobs WHERE blob_id = NEW.blob_id;
    IF b_file_id IS DISTINCT FROM NEW.file_id THEN
        RAISE EXCEPTION 'data_blob_file_embeddings file_id mismatch with data_blobs';
    END IF;
    IF b_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_blob_file_embeddings user_id mismatch with data_blobs';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_blob_file_embeddings_check_consistency
    BEFORE INSERT ON data_blob_file_embeddings
    FOR EACH ROW EXECUTE FUNCTION data_blob_file_embeddings_check_consistency();

-- DEFERRED constraint trigger: at commit, a file's file-embedding rows number
-- either 0 or exactly expected_blob_count. Because each row needs a blob (FK),
-- "== expected_blob_count" implies the whole blob set exists too. The upshot:
-- the mere EXISTENCE of any file-embedding row for a file proves the file is
-- fully processed -- a single cheap EXISTS becomes the readiness probe, and no
-- partial/early-computed embedding set can masquerade as ready.
CREATE FUNCTION data_blob_file_embeddings_check_all_or_none() RETURNS trigger AS $$
DECLARE
    target_file_id BIGINT;
    n_fe INT;
    m_expected INT;
BEGIN
    target_file_id := COALESCE(NEW.file_id, OLD.file_id);
    SELECT count(*) INTO n_fe
    FROM data_blob_file_embeddings WHERE file_id = target_file_id;
    SELECT expected_blob_count INTO m_expected
    FROM data_file_manifests WHERE file_id = target_file_id;
    IF n_fe <> 0 AND (m_expected IS NULL OR n_fe <> m_expected) THEN
        RAISE EXCEPTION
            'data_blob_file_embeddings for file % must be all-or-none (have %, expected %)',
            target_file_id, n_fe, m_expected;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER data_blob_file_embeddings_check_all_or_none
    AFTER INSERT OR DELETE ON data_blob_file_embeddings
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION data_blob_file_embeddings_check_all_or_none();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

-- Lossy: the split data cannot be reassembled. Clear to a fresh slate, then
-- restore the pre-split data_blobs schema.
DELETE FROM data_files;

DROP TABLE IF EXISTS data_blob_file_embeddings;
DROP FUNCTION IF EXISTS data_blob_file_embeddings_check_all_or_none();
DROP FUNCTION IF EXISTS data_blob_file_embeddings_check_consistency();

DROP TRIGGER IF EXISTS data_blobs_check_contiguous ON data_blobs;
DROP FUNCTION IF EXISTS data_blobs_check_contiguous();
DROP TRIGGER IF EXISTS data_blobs_check_against_manifest ON data_blobs;
DROP FUNCTION IF EXISTS data_blobs_check_against_manifest();

ALTER TABLE data_blobs
    DROP CONSTRAINT data_blobs_file_id_fkey,
    ADD CONSTRAINT data_blobs_file_id_fkey
        FOREIGN KEY (file_id) REFERENCES data_files(file_id) ON DELETE CASCADE;

-- Table is empty (cleared above), so NOT NULL columns can be added without a
-- default.
ALTER TABLE data_blobs
    ADD COLUMN is_final_blob BOOLEAN NOT NULL,
    ADD COLUMN next_blob_id BIGINT REFERENCES data_blobs(blob_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    ADD COLUMN embedding_with_file vector(1024) NOT NULL,
    ADD CHECK ((next_blob_id IS NULL) = is_final_blob);

CREATE UNIQUE INDEX data_blobs_one_final_per_file
    ON data_blobs(file_id) WHERE is_final_blob;

DROP TABLE IF EXISTS data_file_manifests;
DROP FUNCTION IF EXISTS data_file_manifests_check_user_id();

CREATE FUNCTION data_blobs_delete_owning_file() RETURNS trigger AS $$
BEGIN
    DELETE FROM data_files WHERE file_id = OLD.file_id;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_blobs_delete_owning_file
    AFTER DELETE ON data_blobs
    FOR EACH ROW EXECUTE FUNCTION data_blobs_delete_owning_file();
