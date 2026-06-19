# app/services/clustering/algorithm.py
from typing import Dict, List, Tuple

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from app.core.config import settings


def _mean_center(vectors: np.ndarray) -> np.ndarray:
    """Subtract the batch mean to counteract embedding anisotropy.

    Gemini embeddings are anisotropic: every vector carries a large shared
    component, so all pairwise cosine similarities sit high and bunched
    together. A single global distance threshold then has no good value — tight
    enough to separate topics shatters each topic into sub-theme fragments
    (the "50 clusters for 16 topics" symptom), loose enough to stop the
    shattering merges unrelated topics into one blob. Removing the common
    component (the batch mean) spreads the similarity distribution back out,
    opening a wide, robust threshold band where topic-level clusters emerge
    cleanly. Same idea as the "all-but-the-top" embedding post-processing.
    """
    X = np.asarray(vectors, dtype=float)
    return X - X.mean(axis=0)


def _auto_distance_threshold(vectors: np.ndarray) -> float:
    """Derive the dendrogram cut height from the data itself.

    Builds the full average-linkage cosine tree and inspects the heights at
    which clusters merge. Sub-theme merges (within one topic) happen low; the
    jump to merging *distinct topics* happens higher. The largest gap between
    consecutive merge heights in the upper region of the tree is that natural
    topic-level boundary, so we cut there. Guarded to only consider cuts that
    leave a sane number of clusters (2..50), so one odd gap can't collapse
    everything into a couple of giant blobs.
    """
    n = len(vectors)
    model = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=0.0,
        metric="cosine",
        linkage="average",
        compute_distances=True,
    ).fit(vectors)
    d = np.sort(model.distances_)            # n-1 merge heights, ascending
    seg = d[int(len(d) * 0.6):]              # upper region only
    if len(seg) < 3:
        return float(np.percentile(d, 75)) if len(d) else 0.5
    mids = (seg[:-1] + seg[1:]) / 2.0
    gaps = np.diff(seg)
    # Clusters remaining if we cut at `mid` = n - (# merges at or below mid).
    kcount = n - np.searchsorted(d, mids, side="right")
    ok = (kcount >= 2) & (kcount <= 50)
    if ok.any():
        idx = np.where(ok)[0]
        return float(mids[idx[np.argmax(gaps[idx])]])
    return float(np.percentile(d, 75))


def _resolve_threshold(raw_setting, vectors: np.ndarray) -> Tuple[float, bool]:
    """Turn settings.CLUSTERING_DISTANCE_THRESHOLD into a concrete cut height.

    "auto" (the default) derives it from the data; any number pins it. Returns
    (threshold, was_auto). Needs >= 2 points to build a tree for auto mode.
    """
    is_auto = isinstance(raw_setting, str) and raw_setting.strip().lower() == "auto"
    if is_auto:
        if len(vectors) >= 2:
            return _auto_distance_threshold(vectors), True
        return 0.5, True  # degenerate batch; value is irrelevant at this size
    return float(raw_setting), False


def run_agglomerative_clustering(
    query_ids: List[int],
    vectors: np.ndarray,
) -> Dict[int, List[int]]:

    n = len(query_ids)
    if n == 0:
        return {}

    # Counteract anisotropy first (see _mean_center): cluster on the centered
    # vectors so the cosine threshold below is actually discriminative.
    X = _mean_center(vectors)
    threshold, was_auto = _resolve_threshold(settings.CLUSTERING_DISTANCE_THRESHOLD, X)

    # Log the EFFECTIVE threshold so it's obvious which value the run used --
    # whether auto-derived or pinned in .env.
    print(
        f"[clustering agglomerative] {n} queries | mean-centered | "
        f"cosine distance_threshold={threshold:.4f} "
        f"({'auto' if was_auto else 'fixed'}) | "
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
        f"If this looks over-fragmented, pin a larger "
        f"CLUSTERING_DISTANCE_THRESHOLD (run tune_threshold.py)."
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