------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

------------------------------------------------------------------------------
-- Data node weights ---------------------------------------------------------
------------------------------------------------------------------------------
-- One row per node holding its centroid (vector aggregate of the subtree's
-- leaf embeddings) and blob_count (size of the leaf subtree). 1:1 with
-- data_nodes by UNIQUE(node_id). Immutable: "recompute" means delete +
-- insert.
--
-- Two invalidation paths converge on this table:
--   * Edge changes (on data_node_edges or data_blob_edges) delete the
--     parent's weight directly (handled in the edges migrations).
--   * Weight changes here cascade upward: a node's centroid is derived
--     from its children's centroids/embeddings, so any insert or delete on
--     this table invalidates the weights of the row's parents. The
--     subsequent DELETE recursively fires the same trigger one level up,
--     propagating invalidation to the root.
CREATE TABLE data_node_weights (
    node_weight_id  BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    node_id         BIGINT NOT NULL UNIQUE REFERENCES data_nodes(node_id) ON DELETE CASCADE,
    centroid        vector(1024) NOT NULL,
    blob_count      INT NOT NULL CHECK (blob_count > 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_data_node_weights_user ON data_node_weights(user_id);

CREATE TRIGGER data_node_weights_prevent_any_update
    BEFORE UPDATE ON data_node_weights
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();


CREATE FUNCTION data_node_weights_check_user_id() RETURNS trigger AS $$
DECLARE
    node_user_id BIGINT;
BEGIN
    SELECT user_id INTO node_user_id FROM data_nodes WHERE node_id = NEW.node_id;
    IF node_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_node_weights user_id mismatch with data_nodes';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_node_weights_check_user_id
    BEFORE INSERT ON data_node_weights
    FOR EACH ROW EXECUTE FUNCTION data_node_weights_check_user_id();


CREATE FUNCTION data_node_weights_invalidate_parents() RETURNS trigger AS $$
DECLARE
    target_node_id BIGINT;
BEGIN
    target_node_id := COALESCE(NEW.node_id, OLD.node_id);
    DELETE FROM data_node_weights
    WHERE node_id IN (
        SELECT parent_node_id FROM data_node_edges
        WHERE child_node_id = target_node_id
    );
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_node_weights_invalidate_parents
    AFTER INSERT OR DELETE ON data_node_weights
    FOR EACH ROW EXECUTE FUNCTION data_node_weights_invalidate_parents();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP FUNCTION IF EXISTS data_node_weights_invalidate_parents();
DROP FUNCTION IF EXISTS data_node_weights_check_user_id();
DROP TABLE IF EXISTS data_node_weights;
