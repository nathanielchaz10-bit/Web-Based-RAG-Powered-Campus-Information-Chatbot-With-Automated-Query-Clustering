"""
Tune CLUSTERING_DISTANCE_THRESHOLD for the agglomerative method against your
OWN data — no API calls, no re-embedding.

The clustering pipeline caches each query's embedding in
query_logs.query_vector, so this script just reloads those cached vectors and
sweeps a range of cosine-distance thresholds, showing how many clusters each
produces and how many queries get clustered vs left as noise. Pick the
threshold that gives a sensible number of topic clusters with good coverage,
then set it in your .env:

    CLUSTERING_DISTANCE_THRESHOLD=<value>

Run from inside hccs_rag_chatbot/:
    python tune_threshold.py

Requires at least one prior clustering run (or seed + run) so the embeddings
are cached. Read-only: it never writes to the database.
"""
import json
import os
import sys

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
import app.models  # noqa: F401  registers ORM models
from app.models.query_log import QueryLog
from app.core.config import settings


def load_vectors():
    db = SessionLocal()
    try:
        rows = (
            db.query(QueryLog.query_id, QueryLog.query_vector)
            .filter(QueryLog.is_valid.is_(True))
            .filter(QueryLog.query_vector.isnot(None))
            .all()
        )
    finally:
        db.close()

    ids, vecs = [], []
    for qid, raw in rows:
        try:
            vecs.append(json.loads(raw))
            ids.append(qid)
        except (TypeError, ValueError):
            continue
    return ids, np.array(vecs)


def main():
    min_size = settings.CLUSTERING_MIN_CLUSTER_SIZE
    ids, vecs = load_vectors()
    n = len(ids)

    if n < min_size:
        print(
            f"Only {n} embedded queries found — need at least {min_size}. "
            "Run clustering once (or seed + run) so embeddings get cached, "
            "then try again."
        )
        return

    print(f"\nLoaded {n} embedded queries (dim={vecs.shape[1]}).\n")

    # Characterize the embedding distribution so the thresholds below make
    # sense: cosine SIMILARITY percentiles across all query pairs.
    sim = cosine_similarity(vecs)
    upper = sim[np.triu_indices(n, k=1)]
    pct = np.percentile(upper, [10, 25, 50, 75, 90])
    print("Pairwise cosine SIMILARITY across all query pairs:")
    print(
        f"  p10={pct[0]:.2f}  p25={pct[1]:.2f}  median={pct[2]:.2f}  "
        f"p75={pct[3]:.2f}  p90={pct[4]:.2f}"
    )
    print(
        "  (If even unrelated pairs sit high, e.g. median > 0.6, you need a "
        "SMALL threshold to separate topics.)\n"
    )

    print(f"Min cluster size (dropped below this): {min_size}")
    print(f"Current .env / default threshold:      {settings.CLUSTERING_DISTANCE_THRESHOLD}\n")

    header = f"{'threshold':>9} | {'clusters':>8} | {'clustered':>9} | {'coverage':>8} | sizes"
    print(header)
    print("-" * len(header))

    rows = []  # (threshold, num_clusters, coverage)
    for th in [round(x, 3) for x in np.arange(0.05, 0.55, 0.025)]:
        labels = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=th,
            metric="cosine",
            linkage="average",
        ).fit_predict(vecs)

        groups = {}
        for label in labels:
            groups[label] = groups.get(label, 0) + 1
        surviving = sorted((s for s in groups.values() if s >= min_size), reverse=True)
        clustered = sum(surviving)
        coverage = clustered / n
        rows.append((th, len(surviving), coverage))
        shown = surviving[:10] + (["..."] if len(surviving) > 10 else [])
        print(
            f"{th:>9.3f} | {len(surviving):>8} | {clustered:>9} | "
            f"{coverage:>7.0%} | {shown}"
        )

    print()
    # Recommend the MIDDLE of the most stable plateau rather than an edge value:
    # a threshold sitting in a wide band that all yield the same sensible
    # cluster count is the most robust to data drift on the next run.
    valid = [(th, k, cov) for th, k, cov in rows if 2 <= k <= 30 and cov >= 0.5]
    if valid:
        # Most common cluster count among valid thresholds = the stable plateau.
        from collections import Counter
        plateau_k = Counter(k for _, k, _ in valid).most_common(1)[0][0]
        plateau_ths = [th for th, k, _ in valid if k == plateau_k]
        pick = plateau_ths[len(plateau_ths) // 2]
        cov = next(c for th, k, c in valid if th == pick and k == plateau_k)
        print(
            f"Suggested starting point: CLUSTERING_DISTANCE_THRESHOLD={pick} "
            f"({plateau_k} clusters, {cov:.0%} of queries clustered)."
        )
        print(
            "That's the middle of the most stable band. Adjust to taste: lower "
            "= more/tighter clusters, higher = fewer/broader. Set it in .env "
            "and restart uvicorn."
        )
    else:
        print(
            "No threshold in the swept range gave a clean 2–30 cluster split — "
            "your embeddings may be unusually tightly packed. Try extending the "
            "sweep below 0.05, or use the LLM method for this data."
        )
    print()


if __name__ == "__main__":
    main()
