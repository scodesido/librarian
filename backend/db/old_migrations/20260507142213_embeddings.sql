-- migrate:up

CREATE EXTENSION IF NOT EXISTS vector;

------------------------------------------------------------------------------
-- Node embeddings -----------------------------------------------------------
------------------------------------------------------------------------------
-- One row per (node, field, model). `field` distinguishes which part of the
-- abstract was encoded ('summary', 'topics', 'running_summary', ...).
-- `model_id` keeps the door open to running multiple encoders side-by-side
-- without dropping rows. Dimension fixed at 1024 (Voyage AI default size).
CREATE TABLE node_embeddings (
    node_id     BIGINT NOT NULL REFERENCES tree_nodes(node_id) ON DELETE CASCADE,
    field       TEXT NOT NULL,
    model_id    TEXT NOT NULL,
    embedding   vector(1024) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (node_id, field, model_id)
);

-- KNN index intentionally not created here. The right choice (HNSW vs
-- IVFFlat, distance metric, whether to partition per (field, model_id))
-- depends on query patterns we don't have yet. Add in a follow-up
-- migration once the retrieval path is wired.


-- migrate:down

DROP TABLE IF EXISTS node_embeddings;

DROP EXTENSION IF EXISTS vector;
