------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

------------------------------------------------------------------------------
-- Data blob edges -----------------------------------------------------------
------------------------------------------------------------------------------
-- Immutable parent->child edges from a height-0 node to a blob. A blob is
-- a leaf of the tree and lives under exactly one parent node, which
-- UNIQUE(child_blob_id) enforces.
--
-- Triggers mirror those on data_node_edges, with the height invariant
-- specialised to parent.height = 0 and the user_id check joining against
-- data_blobs instead of a second data_nodes row.
CREATE TABLE data_blob_edges (
    blob_edge_id    BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_node_id  BIGINT NOT NULL REFERENCES data_nodes(node_id) ON DELETE CASCADE,
    child_blob_id   BIGINT NOT NULL UNIQUE REFERENCES data_blobs(blob_id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_data_blob_edges_user_parent
    ON data_blob_edges(user_id, parent_node_id);

CREATE TRIGGER data_blob_edges_prevent_any_update
    BEFORE UPDATE ON data_blob_edges
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();


CREATE FUNCTION data_blob_edges_check_height() RETURNS trigger AS $$
DECLARE
    parent_height INT;
BEGIN
    SELECT height INTO parent_height FROM data_nodes WHERE node_id = NEW.parent_node_id;
    IF parent_height IS DISTINCT FROM 0 THEN
        RAISE EXCEPTION
            'data_blob_edges parent must have height 0, got %',
            parent_height;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_blob_edges_check_height
    BEFORE INSERT ON data_blob_edges
    FOR EACH ROW EXECUTE FUNCTION data_blob_edges_check_height();


CREATE FUNCTION data_blob_edges_check_user_id() RETURNS trigger AS $$
DECLARE
    parent_user_id BIGINT;
    blob_user_id   BIGINT;
BEGIN
    SELECT user_id INTO parent_user_id FROM data_nodes WHERE node_id = NEW.parent_node_id;
    SELECT user_id INTO blob_user_id  FROM data_blobs WHERE blob_id = NEW.child_blob_id;
    IF parent_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_blob_edges parent user_id mismatch with data_nodes';
    END IF;
    IF blob_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_blob_edges child user_id mismatch with data_blobs';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_blob_edges_check_user_id
    BEFORE INSERT ON data_blob_edges
    FOR EACH ROW EXECUTE FUNCTION data_blob_edges_check_user_id();


CREATE FUNCTION data_blob_edges_invalidate_parent() RETURNS trigger AS $$
DECLARE
    target_parent_id BIGINT;
BEGIN
    target_parent_id := COALESCE(NEW.parent_node_id, OLD.parent_node_id);
    DELETE FROM data_node_weights WHERE node_id = target_parent_id;
    DELETE FROM data_node_abstracts WHERE node_id = target_parent_id;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_blob_edges_invalidate_parent
    AFTER INSERT OR DELETE ON data_blob_edges
    FOR EACH ROW EXECUTE FUNCTION data_blob_edges_invalidate_parent();


CREATE CONSTRAINT TRIGGER data_blob_edges_drop_orphan_parent
    AFTER DELETE ON data_blob_edges
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION data_nodes_drop_if_orphan();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP FUNCTION IF EXISTS data_blob_edges_invalidate_parent();
DROP FUNCTION IF EXISTS data_blob_edges_check_user_id();
DROP FUNCTION IF EXISTS data_blob_edges_check_height();
DROP TABLE IF EXISTS data_blob_edges;
