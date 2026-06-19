# app/services/clustering/health_check.py
"""
Monthly "is the clustering threshold still healthy?" self-check.

The pipeline clusters on a fixed cosine distance threshold
(settings.CLUSTERING_DISTANCE_THRESHOLD, default 0.85, tuned on real data).
That value is robust to query VOLUME but could drift if the *kind* of queries
changes a lot, or if the embedding model is swapped.

What this does (and deliberately does NOT do):
  - It does NOT try to compute the "perfect" threshold automatically. Picking
    the right number of clusters from data alone is unreliable — every simple
    rule we tested either collapses to a couple of blobs or shatters into
    sub-themes (see the rejected auto-mode in git history). That judgement needs
    a human reading tune_threshold.py's table with domain knowledge.
  - It DOES the robust, easy part: detect when the CURRENT threshold is clearly
    malfunctioning — over-merging (everything collapses into one/two blobs) or
    severe over-fragmenting (most queries fall out as sub-min-size noise) — and
    track those health numbers over time so drift is visible.

When it sees a problem it records a recommendation (to system_metrics + logs)
for a human to review, including which DIRECTION to nudge the threshold and a
pointer to re-run tune_threshold.py. It never changes the configured value
itself. Cheap: reads cached embeddings only (no re-embedding / LLM calls).
"""
import json
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from app.core.config import settings
from app.models.query_log import QueryLog
from app.models.system_metrics import SystemMetrics
from app.services.clustering.algorithm import _mean_center

# Below this coverage, clustering is over-fragmenting: most queries are falling
# out as sub-min-size noise, so the threshold is too tight.
MIN_HEALTHY_COVERAGE = 0.30
# If a single cluster holds more than this share of the clustered queries, it's
# a blob: distinct topics have merged together, so the threshold is too loose.
BLOB_FRACTION = 0.60

METRIC_TYPE = "clustering_threshold_check"


def load_cached_vectors(db) -> Tuple[List[int], np.ndarray]:
    """Reload the embeddings cached on valid query logs (no re-embedding)."""
    rows = (
        db.query(QueryLog.query_id, QueryLog.query_vector)
        .filter(QueryLog.is_valid.is_(True))
        .filter(QueryLog.query_vector.isnot(None))
        .all()
    )
    ids, vecs = [], []
    for qid, raw in rows:
        try:
            vecs.append(json.loads(raw))
            ids.append(qid)
        except (TypeError, ValueError):
            continue
    return ids, (np.array(vecs) if vecs else np.empty((0, 0)))


def _evaluate(centered: np.ndarray, threshold: float, min_size: int) -> Dict:
    """Cluster at `threshold` and report health numbers (no ground truth needed)."""
    n = len(centered)
    labels = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=threshold,
        metric="cosine",
        linkage="average",
    ).fit_predict(centered)
    sizes: Dict[int, int] = {}
    for label in labels:
        sizes[label] = sizes.get(label, 0) + 1
    surviving = [s for s in sizes.values() if s >= min_size]
    clustered = sum(surviving)
    return {
        "clusters": len(surviving),
        "coverage": round(clustered / n, 3) if n else 0.0,
        "largest_fraction": round(max(surviving) / clustered, 3) if clustered else 0.0,
    }


def _previous_check(db) -> Dict:
    """The most recent recorded check, for drift comparison (or {} if none)."""
    row = (
        db.query(SystemMetrics)
        .filter(SystemMetrics.metric_type == METRIC_TYPE)
        .order_by(SystemMetrics.timestamp.desc())
        .first()
    )
    if row and row.description:
        try:
            return json.loads(row.description)
        except (TypeError, ValueError):
            return {}
    return {}


def run_threshold_health_check(db, persist: bool = True) -> Dict:
    """Assess whether the configured threshold is still healthy on current data.

    Returns a summary dict and (by default) records it to system_metrics. Never
    mutates the configured threshold — it only flags problems and a direction.
    """
    min_size = settings.CLUSTERING_MIN_CLUSTER_SIZE
    current = float(settings.CLUSTERING_DISTANCE_THRESHOLD)
    ids, vecs = load_cached_vectors(db)
    n = len(ids)

    if n < max(10, min_size * 3):
        result = {
            "status": "insufficient_data",
            "n_queries": n,
            "current_threshold": current,
            "reasons": [f"only {n} embedded queries; need >= {max(10, min_size * 3)}"],
        }
        if persist:
            _persist(db, result["n_queries"], result)
        _log(result)
        return result

    centered = _mean_center(vecs)
    ev = _evaluate(centered, current, min_size)

    reasons: List[str] = []
    # Over-fragmenting: most queries fall out as sub-min-size noise (too tight).
    over_fragmenting = ev["coverage"] < MIN_HEALTHY_COVERAGE
    # Over-merging: distinct topics collapse into one/a-dominant blob (too loose).
    # Requires >= 1 surviving cluster — zero clusters is fragmentation, not a blob.
    over_merging = ev["clusters"] >= 1 and (
        ev["clusters"] == 1 or ev["largest_fraction"] > BLOB_FRACTION
    )
    if over_fragmenting:
        reasons.append(
            f"over-fragmenting: only {ev['coverage']:.0%} of queries clustered "
            f"(< {MIN_HEALTHY_COVERAGE:.0%}) — threshold likely too tight"
        )
    if over_merging:
        reasons.append(
            f"over-merging: {ev['clusters']} cluster(s), largest holds "
            f"{ev['largest_fraction']:.0%} of clustered queries — threshold likely too loose"
        )
    # If both somehow flag, treat under-coverage as the dominant problem to fix.
    direction = "raise" if over_fragmenting else ("lower" if over_merging else None)

    # Drift note: compare to the previous check so a slow change is visible even
    # if neither check individually trips a hard threshold.
    prev = _previous_check(db)
    if prev.get("coverage") is not None:
        d = ev["coverage"] - prev["coverage"]
        if abs(d) >= 0.20:
            reasons.append(
                f"coverage shifted {d:+.0%} since the last check "
                f"({prev['coverage']:.0%} -> {ev['coverage']:.0%})"
            )

    result = {
        "status": "review_recommended" if reasons else "ok",
        "n_queries": n,
        "current_threshold": current,
        "clusters": ev["clusters"],
        "coverage": ev["coverage"],
        "largest_fraction": ev["largest_fraction"],
        "suggested_direction": direction,  # "raise" | "lower" | None
        "reasons": reasons,
    }
    if persist:
        _persist(db, ev["coverage"], result)
    _log(result)
    return result


def _persist(db, metric_value: float, result: Dict) -> None:
    """Append the check to system_metrics as an audit/drift trail."""
    db.add(SystemMetrics(
        metric_type=METRIC_TYPE,
        metric_value=float(metric_value),
        timestamp=datetime.utcnow(),
        description=json.dumps(result),
    ))
    db.commit()


def _log(result: Dict) -> None:
    status = result["status"]
    if status == "ok":
        print(
            f"[clustering health-check] OK — threshold "
            f"{result['current_threshold']:.2f} still healthy "
            f"({result['clusters']} clusters, {result['coverage']:.0%} coverage, "
            f"largest {result['largest_fraction']:.0%}, n={result['n_queries']})."
        )
    elif status == "review_recommended":
        print(f"[clustering health-check] REVIEW RECOMMENDED (n={result['n_queries']}):")
        for r in result["reasons"]:
            print(f"  - {r}")
        d = result.get("suggested_direction")
        hint = f" (try a {'higher' if d == 'raise' else 'lower'} value)" if d else ""
        print(
            f"  -> re-run `python tune_threshold.py` and re-pick "
            f"CLUSTERING_DISTANCE_THRESHOLD{hint}. Recorded to system_metrics."
        )
    else:
        print(f"[clustering health-check] {status}: {'; '.join(result.get('reasons', []))}")


if __name__ == "__main__":
    # On-demand run: `python -m app.services.clustering.health_check`
    from app.core.database import SessionLocal
    _db = SessionLocal()
    try:
        run_threshold_health_check(_db)
    finally:
        _db.close()
