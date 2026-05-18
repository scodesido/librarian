------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

------------------------------------------------------------------------------
-- Data nodes ----------------------------------------------------------------
------------------------------------------------------------------------------
-- Immutable internal nodes of the per-user abstraction tree. A node exists
-- only as long as it has at least one outgoing edge (a node_edge where it
-- is the parent, or a blob_edge where it is the parent), or it is the
-- per-user root.
--
-- Two correctness invariants are enforced as DEFERRABLE INITIALLY DEFERRED
-- constraint triggers so that within a single transaction the tree can be
-- restructured (e.g. swap the root, move a child between parents) without
-- transiently violating them:
--
--   * at most one is_root = TRUE per user (data_nodes_check_root_unique).
--   * a non-root node with no outgoing edges is dropped at commit time
--     (data_nodes_drop_if_orphan, invoked from triggers on the two edge
--     tables in the following migrations).
--
-- The drop-if-orphan cascade collapses orphan subtrees naturally: deleting
-- the orphaned node cascades to its incoming edges, which fire the same
-- trigger one level up, until the cascade hits either a still-anchored
-- node or the root.
CREATE TABLE data_nodes (
    node_id     BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    is_root     BOOLEAN NOT NULL DEFAULT FALSE,
    height      INT NOT NULL CHECK (height >= 0),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_data_nodes_user_height ON data_nodes(user_id, height);
CREATE INDEX idx_data_nodes_user_root ON data_nodes(user_id) WHERE is_root;

CREATE TRIGGER data_nodes_prevent_any_update
    BEFORE UPDATE ON data_nodes
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();


-- Deferred at-most-one-root-per-user check. Partial UNIQUE indexes can't
-- be deferred in Postgres, so the check is implemented as a deferred
-- constraint trigger. The trigger only fires on insertion of a row with
-- is_root = TRUE; rows are immutable, so that is the only path by which a
-- second root could ever exist.
CREATE FUNCTION data_nodes_check_root_unique() RETURNS trigger AS $$
DECLARE
    root_count INT;
BEGIN
    SELECT count(*) INTO root_count
    FROM data_nodes
    WHERE user_id = NEW.user_id AND is_root = TRUE;
    IF root_count > 1 THEN
        RAISE EXCEPTION 'user % has more than one root node', NEW.user_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER data_nodes_check_root_unique
    AFTER INSERT ON data_nodes
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    WHEN (NEW.is_root = TRUE)
    EXECUTE FUNCTION data_nodes_check_root_unique();


-- Drop a node iff it is non-root and has no outgoing edges. Invoked as a
-- deferred constraint trigger from data_node_edges and data_blob_edges
-- AFTER DELETE; the deleted edge's parent_node_id is the candidate.
--
-- The body references data_node_edges and data_blob_edges, which are
-- created in subsequent migrations. PL/pgSQL defers symbol resolution to
-- invocation time, so creation here is fine; the function is never invoked
-- until both tables exist.
CREATE FUNCTION data_nodes_drop_if_orphan() RETURNS trigger AS $$
BEGIN
    DELETE FROM data_nodes dn
    WHERE dn.node_id = OLD.parent_node_id
      AND dn.is_root = FALSE
      AND NOT EXISTS (SELECT 1 FROM data_node_edges
                      WHERE parent_node_id = dn.node_id)
      AND NOT EXISTS (SELECT 1 FROM data_blob_edges
                      WHERE parent_node_id = dn.node_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP FUNCTION IF EXISTS data_nodes_drop_if_orphan();
DROP FUNCTION IF EXISTS data_nodes_check_root_unique();
DROP TABLE IF EXISTS data_nodes;
