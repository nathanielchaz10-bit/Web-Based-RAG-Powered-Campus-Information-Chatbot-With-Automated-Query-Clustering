# app/services/clustering/algorithm.py
from typing import Dict, List

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize

DISTANCE_THRESHOLD = 0.35
MIN_CLUSTER_SIZE = 3


def run_agglomerative_clustering(
    query_ids: List[int],
    vectors: np.ndarray,
) -> Dict[int, List[int]]:

    n = len(query_ids)
    if n == 0:
        return {}
    normed = normalize(np.asarray(vectors))

    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=DISTANCE_THRESHOLD,
        metric="euclidean",
        linkage="average",
    )
    labels = model.fit_predict(normed)

    raw_groups: Dict[int, List[int]] = {}
    for query_id, label in zip(query_ids, labels):
        raw_groups.setdefault(int(label), []).append(query_id)

    # Drop noise clusters below the minimum size threshold.
    groups = {
        label: members
        for label, members in raw_groups.items()
        if len(members) >= MIN_CLUSTER_SIZE
    }

    return groups


def compute_centroid(vectors: np.ndarray) -> np.ndarray:
    """Mean vector for a cluster, stored as Cluster.centroid_vector.

    Used later to assign newly-arriving queries to an existing cluster by
    nearest-centroid lookup without re-running full clustering (a possible
    future optimization — not required by the current rebuild-from-scratch
    flow, but cheap to compute now while we already have the vectors in hand).
    """
    return np.asarray(vectors).mean(axis=0)