------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

------------------------------------------------------------------------------
-- Data node abstracts -------------------------------------------------------
------------------------------------------------------------------------------
-- One row per node holding its LLM-generated Abstract (JSONB). 1:1 with
-- data_nodes by UNIQUE(node_id). Immutable.
--
-- Cascade invalidation mirrors data_node_weights: a node's abstract is
-- computed from its children's abstracts, so any insert or delete on this
-- table invalidates the abstracts of the row's parents. The recursive
-- DELETE propagates the invalidation upward to the root.
--
-- The edge-side triggers (in data_node_edges, data_blob_edges) already
-- invalidate the parent's abstract on structural change; this trigger
-- handles the orthogonal case where the structure is stable but a deeper
-- subtree's abstract was regenerated.
CREATE TABLE data_node_abstracts (
    node_abstract_id  BIGSERIAL PRIMARY KEY,
    user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    node_id           BIGINT NOT NULL UNIQUE REFERENCES data_nodes(node_id) ON DELETE CASCADE,
    abstract          JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_data_node_abstracts_user ON data_node_abstracts(user_id);

CREATE TRIGGER data_node_abstracts_prevent_any_update
    BEFORE UPDATE ON data_node_abstracts
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();


CREATE FUNCTION data_node_abstracts_check_user_id() RETURNS trigger AS $$
DECLARE
    node_user_id BIGINT;
BEGIN
    SELECT user_id INTO node_user_id FROM data_nodes WHERE node_id = NEW.node_id;
    IF node_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_node_abstracts user_id mismatch with data_nodes';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_node_abstracts_check_user_id
    BEFORE INSERT ON data_node_abstracts
    FOR EACH ROW EXECUTE FUNCTION data_node_abstracts_check_user_id();


CREATE FUNCTION data_node_abstracts_invalidate_parents() RETURNS trigger AS $$
DECLARE
    target_node_id BIGINT;
BEGIN
    target_node_id := COALESCE(NEW.node_id, OLD.node_id);
    DELETE FROM data_node_abstracts
    WHERE node_id IN (
        SELECT parent_node_id FROM data_node_edges
        WHERE child_node_id = target_node_id
    );
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_node_abstracts_invalidate_parents
    AFTER INSERT OR DELETE ON data_node_abstracts
    FOR EACH ROW EXECUTE FUNCTION data_node_abstracts_invalidate_parents();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP FUNCTION IF EXISTS data_node_abstracts_invalidate_parents();
DROP FUNCTION IF EXISTS data_node_abstracts_check_user_id();
DROP TABLE IF EXISTS data_node_abstracts;
