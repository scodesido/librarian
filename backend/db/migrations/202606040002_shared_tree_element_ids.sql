-- migrate:up

-- Shared id space for tree elements (see docs/20.retrieval_ref_integrity.md).
--
-- node_id and blob_id were independent per-table sequences, both starting at 1,
-- so a single integer could be a valid node id AND a valid (unrelated) blob id
-- at once. The retrieval agent could exploit that: reuse a node id it just saw
-- as a `b:` blob ref and silently land on the wrong file. A single sequence
-- feeding both columns makes a node id and a blob id never coincide, so a
-- cross-kind ref can no longer resolve.
--
-- The shared sequence only governs NEW inserts, so disjointness holds only on a
-- rebuilt tree. Existing rows keep their (possibly colliding) ids: this
-- migration deliberately does NOT touch data — clearing and re-syncing is an
-- operator action, run separately once this is applied. Until that rebuild the
-- old ids remain, so the provenance gate (docs/20) is the load-bearing
-- protection in the meantime.
CREATE SEQUENCE data_tree_element_id_seq;

-- Seed the sequence past the high-water mark of both columns so live ids never
-- collide with already-issued ones, whether or not any data is present. `false`
-- => the value given is the next one handed out.
SELECT setval(
    'data_tree_element_id_seq',
    GREATEST(
        COALESCE((SELECT max(node_id) FROM data_nodes), 0),
        COALESCE((SELECT max(blob_id) FROM data_blobs), 0)
    ) + 1,
    false
);

ALTER TABLE data_nodes ALTER COLUMN node_id SET DEFAULT nextval('data_tree_element_id_seq');
ALTER TABLE data_blobs ALTER COLUMN blob_id SET DEFAULT nextval('data_tree_element_id_seq');

-- migrate:down

-- Restore the per-table sequence defaults (left in place, OWNED BY their
-- columns, so this is a straight swap-back) and drop the shared one.
ALTER TABLE data_nodes ALTER COLUMN node_id SET DEFAULT nextval('data_nodes_node_id_seq');
ALTER TABLE data_blobs ALTER COLUMN blob_id SET DEFAULT nextval('data_blobs_blob_id_seq');

DROP SEQUENCE data_tree_element_id_seq;
