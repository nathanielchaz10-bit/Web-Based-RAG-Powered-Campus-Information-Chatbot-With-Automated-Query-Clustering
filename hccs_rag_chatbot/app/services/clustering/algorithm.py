# app/services/clustering/algorithm.py
from typing import Dict, List

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from app.core.config import settings


def run_agglomerative_clustering(
    query_ids: List[int],
    vectors: np.ndarray,
) -> Dict[int, List[int]]:

    n = len(query_ids)
    if n == 0:
        return {}

    # Log the EFFECTIVE threshold so it's obvious which value the run used --
    # the #1 cause of "only 1 cluster" is .env not actually setting this (so it
    # falls back to the default) or being edited in the wrong file.
    print(
        f"[clustering agglomerative] {n} queries | "
        f"cosine distance_threshold={settings.CLUSTERING_DISTANCE_THRESHOLD} | "
        f"min_cluster_size={settings.CLUSTERING_MIN_CLUSTER_SIZE}"
    )

    # Cluster on COSINE distance directly (distance = 1 - cosine similarity):
    # two queries are "close" when their embeddings point the same semantic
    # direction, regardless of magnitude. This is the natural metric for text
    # embeddings and makes the threshold directly interpretable.
    #
    # Earlier this normalized the vectors and used euclidean distance with a
    # 0.35 threshold, which on unit vectors only merged queries with cosine
    # similarity >= ~0.94 (near-duplicate tightness) — so almost every query
    # ended up a singleton and only one accidental group survived the min-size
    # filter. Cosine + a topic-level threshold fixes that fragmentation.
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=settings.CLUSTERING_DISTANCE_THRESHOLD,
        metric="cosine",
        linkage="average",
    )
    labels = model.fit_predict(np.asarray(vectors))

    raw_groups: Dict[int, List[int]] = {}
    for query_id, label in zip(query_ids, labels):
        raw_groups.setdefault(int(label), []).append(query_id)

    # Drop noise clusters below the minimum size threshold, then re-key the
    # survivors as contiguous 0-based labels. sklearn assigns arbitrary,
    # non-contiguous cluster ids (e.g. {3, 17, 42}); the downstream LLM labeler
    # echoes the cluster numbers back as JSON keys, and it does that far more
    # reliably for small, clean 0..k-1 labels than for sparse ids. (The LLM
    # method already emits contiguous labels, which is why its labeling was
    # reliable while the agglomerative path's was flaky.)
    min_size = settings.CLUSTERING_MIN_CLUSTER_SIZE
    surviving = [members for members in raw_groups.values() if len(members) >= min_size]
    groups = {label: members for label, members in enumerate(surviving)}

    print(
        f"[clustering agglomerative] raw groups={len(raw_groups)} -> "
        f"{len(groups)} clusters (>= min size) covering "
        f"{sum(len(m) for m in groups.values())}/{n} queries. "
        f"If this is 1, lower CLUSTERING_DISTANCE_THRESHOLD; if it's near {n} "
        f"singletons, raise it."
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