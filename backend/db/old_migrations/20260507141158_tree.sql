-- migrate:up

------------------------------------------------------------------------------
-- Tree state ----------------------------------------------------------------
------------------------------------------------------------------------------
-- One row per user. `level` is the gate the workers coordinate on:
--   level = 0 -> leaves are still being built (or no work yet)
--   level = K (K >= 1) -> Worker 2 may build parents at height K, but only
--                         once all height-(K-1) nodes are READY
CREATE TABLE tree_state (
    user_id     BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    level       INT NOT NULL DEFAULT 0 CHECK (level >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER tree_state_set_updated_at
    BEFORE UPDATE ON tree_state
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


------------------------------------------------------------------------------
-- Tree nodes ----------------------------------------------------------------
------------------------------------------------------------------------------
-- Leaves (height = 0) are created READY in the same transaction as their
-- blob. Internal nodes (height > 0) are created PENDING by Worker 2 and
-- transitioned to READY by Worker 3 once their abstract is computed.
CREATE TABLE tree_nodes (
    node_id     BIGSERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blob_id     BIGINT UNIQUE REFERENCES data_blobs(blob_id) ON DELETE CASCADE,
    abstract    JSONB,
    height      INT NOT NULL CHECK (height >= 0),
    state       TEXT NOT NULL
                CHECK (state IN ('PENDING', 'PROCESSING', 'READY', 'FAILED')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT tree_nodes_leaf_invariant CHECK (
        (height = 0 AND blob_id IS NOT NULL AND state = 'READY')
        OR (height > 0 AND blob_id IS NULL)
    )
);

CREATE INDEX idx_tree_nodes_user_height_state
    ON tree_nodes(user_id, height, state);

CREATE TRIGGER tree_nodes_set_updated_at
    BEFORE UPDATE ON tree_nodes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER tree_nodes_prevent_created_at_change
    BEFORE UPDATE ON tree_nodes
    FOR EACH ROW EXECUTE FUNCTION prevent_created_at_change();


------------------------------------------------------------------------------
-- Tree edges ----------------------------------------------------------------
------------------------------------------------------------------------------
-- DAG, not strict tree: a node may have multiple parents. Heights are
-- enforced by trigger (parent.height = child.height + 1), giving a layered
-- DAG with no cycles by construction.
CREATE TABLE tree_edges (
    edge_id     BIGSERIAL PRIMARY KEY,
    parent_id   BIGINT NOT NULL REFERENCES tree_nodes(node_id) ON DELETE CASCADE,
    child_id    BIGINT NOT NULL REFERENCES tree_nodes(node_id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (parent_id, child_id),
    CHECK (parent_id <> child_id)
);

CREATE INDEX idx_tree_edges_child_id ON tree_edges(child_id);


-- Enforce parent.height = child.height + 1.
CREATE FUNCTION tree_edges_check_height() RETURNS trigger AS $$
DECLARE
    parent_height INT;
    child_height  INT;
BEGIN
    SELECT height INTO parent_height FROM tree_nodes WHERE node_id = NEW.parent_id;
    SELECT height INTO child_height  FROM tree_nodes WHERE node_id = NEW.child_id;
    IF parent_height IS DISTINCT FROM child_height + 1 THEN
        RAISE EXCEPTION
            'tree_edges height mismatch: parent height %, child height %, '
            'expected parent height %',
            parent_height, child_height, child_height + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tree_edges_check_height
    BEFORE INSERT OR UPDATE ON tree_edges
    FOR EACH ROW EXECUTE FUNCTION tree_edges_check_height();


-- After deleting an edge, if the parent has no remaining outgoing edges,
-- delete the parent. This recurses naturally through the cascade chain:
-- deleting the parent cascades to its incoming edges, which fire this
-- trigger again at the next level up. A whole orphan ancestor subtree
-- collapses on a single leaf removal.
CREATE FUNCTION tree_edges_delete_orphan_parent() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM tree_edges WHERE parent_id = OLD.parent_id
    ) THEN
        DELETE FROM tree_nodes WHERE node_id = OLD.parent_id;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tree_edges_delete_orphan_parent
    AFTER DELETE ON tree_edges
    FOR EACH ROW EXECUTE FUNCTION tree_edges_delete_orphan_parent();


-- migrate:down

DROP TRIGGER IF EXISTS tree_edges_delete_orphan_parent ON tree_edges;
DROP TRIGGER IF EXISTS tree_edges_check_height ON tree_edges;
DROP FUNCTION IF EXISTS tree_edges_delete_orphan_parent();
DROP FUNCTION IF EXISTS tree_edges_check_height();

DROP TABLE IF EXISTS tree_edges;
DROP TABLE IF EXISTS tree_nodes;
DROP TABLE IF EXISTS tree_state;
