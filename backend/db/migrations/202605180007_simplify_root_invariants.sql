------------------------------------------------------------------------------
-- Up ------------------------------------------------------------------------
------------------------------------------------------------------------------
-- migrate:up

-- Drop orphan roots too, not just orphan non-roots.
--
-- The previous definition of data_nodes_drop_if_orphan excluded
-- is_root = TRUE nodes from the cleanup, on the implicit assumption
-- that a per-user root is a useful placeholder even when empty. In
-- practice, an empty root leaves the tree in a structurally weird
-- state (a height>0 node with zero children after a deep cascade),
-- which tree_builder workers can't process. And nothing depends on
-- the placeholder: tree_builder's insert path already creates the
-- root lazily via find_root → nodes.create, and the API endpoint
-- returns a graceful 404 when no root exists.
--
-- The new definition lets the orphan-collection cascade run all the
-- way up to and through the root. A subsequent insertion rebuilds
-- the tree from scratch.
CREATE OR REPLACE FUNCTION data_nodes_drop_if_orphan() RETURNS trigger AS $$
BEGIN
    DELETE FROM data_nodes dn
    WHERE dn.node_id = OLD.parent_node_id
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

CREATE OR REPLACE FUNCTION data_nodes_drop_if_orphan() RETURNS trigger AS $$
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
