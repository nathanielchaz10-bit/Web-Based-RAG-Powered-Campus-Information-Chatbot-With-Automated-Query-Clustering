# app/services/clustering/algorithm.py
from typing import Dict, List

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from app.core.config import settings


def _mean_center(vectors: np.ndarray) -> np.ndarray:
    """Subtract the batch mean to counteract embedding anisotropy.

    Gemini embeddings are anisotropic: every vector carries a large shared
    component, so all pairwise cosine similarities sit high and bunched
    together (on real data, raw similarity median ~0.83). A single global
    distance threshold then has no good value — tight enough to separate topics
    shatters each topic into sub-theme fragments (the "50 clusters for 16
    topics" symptom), loose enough to stop the shattering merges unrelated
    topics into one blob. Removing the common component (the batch mean) spreads
    the similarity distribution back out (centered median ~0 with a wide
    spread), opening a usable threshold band where topic-level clusters emerge
    cleanly. Same idea as the "all-but-the-top" embedding post-processing.
    """
    X = np.asarray(vectors, dtype=float)
    return X - X.mean(axis=0)


def run_agglomerative_clustering(
    query_ids: List[int],
    vectors: np.ndarray,
) -> Dict[int, List[int]]:

    n = len(query_ids)
    if n == 0:
        return {}

    # Counteract anisotropy first (see _mean_center): cluster on the centered
    # vectors so the cosine threshold below is actually discriminative. Because
    # centering pushes unrelated pairs apart, the useful threshold lives higher
    # than on raw vectors (~0.85 vs the old ~0.25) — re-tune with
    # tune_threshold.py if you change embedding models or your query mix shifts.
    X = _mean_center(vectors)
    threshold = settings.CLUSTERING_DISTANCE_THRESHOLD

    # Log the EFFECTIVE threshold so it's obvious which value the run used.
    print(
        f"[clustering agglomerative] {n} queries | mean-centered | "
        f"cosine distance_threshold={threshold} | "
        f"min_cluster_size={settings.CLUSTERING_MIN_CLUSTER_SIZE}"
    )

    # Cluster on COSINE distance directly (distance = 1 - cosine similarity):
    # two queries are "close" when their (centered) embeddings point the same
    # semantic direction. This is the natural metric for text embeddings and
    # makes the threshold directly interpretable.
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        metric="cosine",
        linkage="average",
    )
    labels = model.fit_predict(X)

    raw_groups: Dict[int, List[int]] = {}
    for query_id, label in zip(query_ids, labels):
        raw_groups.setdefault(int(label), []).append(query_id)

    # Drop noise clusters below the minimum size threshold, then re-key the
    # survivors as contiguous 0-based labels. sklearn assigns arbitrary,
    # non-contiguous cluster ids (e.g. {3, 17, 42}); the downstream LLM labeler
    # echoes the cluster numbers back as JSON keys, and it does that far more
    # reliably for small, clean 0..k-1 labels than for sparse ids.
    min_size = settings.CLUSTERING_MIN_CLUSTER_SIZE
    surviving = [members for members in raw_groups.values() if len(members) >= min_size]
    groups = {label: members for label, members in enumerate(surviving)}

    print(
        f"[clustering agglomerative] raw groups={len(raw_groups)} -> "
        f"{len(groups)} clusters (>= min size) covering "
        f"{sum(len(m) for m in groups.values())}/{n} queries. "
        f"If over-fragmented (near {n} singletons) raise "
        f"CLUSTERING_DISTANCE_THRESHOLD; if it collapses to 1-2 blobs, lower it "
        f"(run tune_threshold.py)."
    )

    return groups


def compute_centroid(vectors: np.ndarray) -> np.ndarray:
    """Mean vector for a cluster, stored as Cluster.centroid_vector.

    Used later to assign newly-arriving queries to an existing cluster by
    nearest-centroid lookup without re-running full clustering (a possible
    future optimization — not required by the current rebuild-from-scratch
    flow, but cheap to compute now while we already have the vectors in hand).
    """
    return np.asarray(vectors).mean(axis=0)