import numpy as np
from numpy.typing import NDArray


def normalize_l2(vec: NDArray[np.float32]) -> NDArray[np.float32]:
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return (vec / norm).astype(np.float32)


def euclidean(a: NDArray[np.float32], b: NDArray[np.float32]) -> float:
    return float(np.linalg.norm(a - b))


def weighted_distance(
    emb: NDArray[np.float32],
    child_centroid: NDArray[np.float32],
    child_blob_count: int,
    mean_blob_count: float,
    alpha: float,
) -> float:
    """Distance from `emb` to `child_centroid`, biased by how populated the
    child's subtree is relative to its siblings.

    With alpha > 0 a child that already holds many blobs looks proportionally
    farther, so descent/assignment prefer less-populated subtrees. With
    alpha = 0 the formula collapses to pure euclidean distance.

    Both centroids and blob `embedding_with_file` vectors are L2-unit
    (centroids are normalized after the average / weighted average), so the
    raw distance is bounded in [0, 2].
    """
    d = euclidean(emb, child_centroid)
    if mean_blob_count == 0.0:
        return d
    return d * (child_blob_count / mean_blob_count) ** alpha
