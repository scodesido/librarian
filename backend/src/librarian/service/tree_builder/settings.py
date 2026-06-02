from pydantic import BaseModel, Field


class TreeBuilderSettings(BaseModel):
    # Worker loop
    poll_interval_seconds: float = 5.0
    concurrent_workers: int = 1

    # Error handling: per-worker exponential backoff.
    error_backoff_initial_seconds: float = 5.0
    error_backoff_max_seconds: float = 300.0
    error_backoff_multiplier: float = 2.0

    # Worker-event throttle: a failure of the same (code, source) for the
    # same user within this window is not re-recorded. See
    # docs/15.user_worker_events.md.
    event_throttle_seconds: float = 600.0

    # Tree shape parameters.
    #
    # max_children_per_node (K): once a node has more than K children, the
    # rebalance step splits it. Must be > 2 (a split produces 2 new nodes;
    # K=2 would mean the splits can never reduce the count below the
    # threshold and the tree would never settle).
    #
    # imbalance_alpha: exponent in the descent/split distance formula
    # `distance(emb, child_centroid) * (blob_count / mean_blob_count)^alpha`.
    # Larger alpha biases harder against already-populated subtrees.
    max_children_per_node: int = Field(default=4, gt=2)
    imbalance_alpha: float = 0.1
