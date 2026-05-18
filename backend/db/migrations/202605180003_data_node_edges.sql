------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

------------------------------------------------------------------------------
-- Data node edges -----------------------------------------------------------
------------------------------------------------------------------------------
-- Immutable parent->child edges between two nodes one level apart.
--
-- Triggers:
--   * height invariant: parent.height = child.height + 1.
--   * user_id consistency: parent.user_id = child.user_id = NEW.user_id.
--   * weight/abstract invalidation: any structural change to the parent's
--     child set invalidates the parent's node_weight and node_abstract.
--   * deferred orphan-collection (data_nodes_drop_if_orphan, from the
--     data_nodes migration): a parent left childless by a delete is
--     dropped at commit time unless it is the root.
CREATE TABLE data_node_edges (
    node_edge_id    BIGSERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_node_id  BIGINT NOT NULL REFERENCES data_nodes(node_id) ON DELETE CASCADE,
    child_node_id   BIGINT NOT NULL REFERENCES data_nodes(node_id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (parent_node_id, child_node_id),
    CHECK (parent_node_id <> child_node_id)
);

CREATE INDEX idx_data_node_edges_child ON data_node_edges(child_node_id);
CREATE INDEX idx_data_node_edges_user_parent
    ON data_node_edges(user_id, parent_node_id);

CREATE TRIGGER data_node_edges_prevent_any_update
    BEFORE UPDATE ON data_node_edges
    FOR EACH ROW EXECUTE FUNCTION prevent_any_update();


CREATE FUNCTION data_node_edges_check_height() RETURNS trigger AS $$
DECLARE
    parent_height INT;
    child_height  INT;
BEGIN
    SELECT height INTO parent_height FROM data_nodes WHERE node_id = NEW.parent_node_id;
    SELECT height INTO child_height  FROM data_nodes WHERE node_id = NEW.child_node_id;
    IF parent_height IS DISTINCT FROM child_height + 1 THEN
        RAISE EXCEPTION
            'data_node_edges height mismatch: parent height %, child height %, '
            'expected parent height %',
            parent_height, child_height, child_height + 1;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_node_edges_check_height
    BEFORE INSERT ON data_node_edges
    FOR EACH ROW EXECUTE FUNCTION data_node_edges_check_height();


CREATE FUNCTION data_node_edges_check_user_id() RETURNS trigger AS $$
DECLARE
    parent_user_id BIGINT;
    child_user_id  BIGINT;
BEGIN
    SELECT user_id INTO parent_user_id FROM data_nodes WHERE node_id = NEW.parent_node_id;
    SELECT user_id INTO child_user_id  FROM data_nodes WHERE node_id = NEW.child_node_id;
    IF parent_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_node_edges parent user_id mismatch with data_nodes';
    END IF;
    IF child_user_id IS DISTINCT FROM NEW.user_id THEN
        RAISE EXCEPTION 'data_node_edges child user_id mismatch with data_nodes';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_node_edges_check_user_id
    BEFORE INSERT ON data_node_edges
    FOR EACH ROW EXECUTE FUNCTION data_node_edges_check_user_id();


-- Invalidate the parent's weight and abstract on any structural change to
-- its child set. Body references data_node_weights and data_node_abstracts
-- which are created in later migrations; PL/pgSQL resolves at invocation
-- time, so creation here is fine.
CREATE FUNCTION data_node_edges_invalidate_parent() RETURNS trigger AS $$
DECLARE
    target_parent_id BIGINT;
BEGIN
    target_parent_id := COALESCE(NEW.parent_node_id, OLD.parent_node_id);
    DELETE FROM data_node_weights WHERE node_id = target_parent_id;
    DELETE FROM data_node_abstracts WHERE node_id = target_parent_id;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER data_node_edges_invalidate_parent
    AFTER INSERT OR DELETE ON data_node_edges
    FOR EACH ROW EXECUTE FUNCTION data_node_edges_invalidate_parent();


CREATE CONSTRAINT TRIGGER data_node_edges_drop_orphan_parent
    AFTER DELETE ON data_node_edges
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION data_nodes_drop_if_orphan();


------------------------------------------------------------------------------
-- Down ----------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:down

DROP FUNCTION IF EXISTS data_node_edges_invalidate_parent();
DROP FUNCTION IF EXISTS data_node_edges_check_user_id();
DROP FUNCTION IF EXISTS data_node_edges_check_height();
DROP TABLE IF EXISTS data_node_edges;
