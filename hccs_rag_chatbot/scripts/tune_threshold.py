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
    python scripts/tune_threshold.py

Requires at least one prior clustering run (or seed + run) so the embeddings
are cached. Read-only: it never writes to the database.
"""
import json
import os
import sys

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity

# This script lives in hccs_rag_chatbot/scripts/; add the app root (its parent)
# to the path so `import app...` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
import app.models  # noqa: F401  registers ORM models
from app.models.query_log import QueryLog
from app.core.config import settings
from app.services.clustering.algorithm import _mean_center


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

    # Clustering runs on the MEAN-CENTERED vectors (counteracts Gemini's
    # anisotropy), so tune on the same space the pipeline actually sees.
    centered = _mean_center(vecs)

    # Characterize the embedding distribution so the thresholds below make
    # sense: cosine SIMILARITY percentiles across all query pairs, raw vs
    # centered. Centering should pull unrelated pairs down toward ~0, which is
    # what opens up a usable threshold band.
    def _pct(V):
        s = cosine_similarity(V)[np.triu_indices(n, k=1)]
        return np.percentile(s, [10, 25, 50, 75, 90])

    raw_pct, cen_pct = _pct(vecs), _pct(centered)
    print("Pairwise cosine SIMILARITY across all query pairs (p10/median/p90):")
    print(f"  raw:      {raw_pct[0]:.2f} / {raw_pct[2]:.2f} / {raw_pct[4]:.2f}")
    print(f"  centered: {cen_pct[0]:.2f} / {cen_pct[2]:.2f} / {cen_pct[4]:.2f}")
    print(
        "  (Centered median near 0 with a wide spread is what you want — it "
        "means topics are separable by a single threshold.)\n"
    )

    print(f"Min cluster size (dropped below this): {min_size}")
    print(f"Current .env / default threshold:      {settings.CLUSTERING_DISTANCE_THRESHOLD}\n")

    header = f"{'threshold':>9} | {'clusters':>8} | {'clustered':>9} | {'coverage':>8} | sizes"
    print(header)
    print("-" * len(header))

    rows = []  # (threshold, num_clusters, coverage)
    for th in [round(x, 3) for x in np.arange(0.05, 1.0, 0.05)]:
        labels = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=th,
            metric="cosine",
            linkage="average",
        ).fit_predict(centered)

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
    # Suggest the MOST-RESOLVED split: the threshold giving the highest number
    # of surviving clusters (tie-broken by coverage). As the threshold rises,
    # cluster count climbs (queries clear the min-size bar) then falls again as
    # distinct topics merge into blobs, so this peak sits right at "as many real
    # topic groups as the data supports, just before they start merging."
    valid = [(th, k, cov) for th, k, cov in rows if 2 <= k <= 30 and cov >= 0.4]
    if valid:
        pick, k, cov = max(valid, key=lambda r: (r[1], r[2]))
        print(
            f"Suggested: CLUSTERING_DISTANCE_THRESHOLD={pick} "
            f"-> {k} clusters, {cov:.0%} of queries clustered "
            f"(the most-resolved split before topics merge into blobs)."
        )
        print(
            "Adjust to taste: lower = more/tighter clusters, higher = "
            "fewer/broader (too high merges topics into blobs). Set it in .env "
            "and restart uvicorn."
        )
    else:
        print(
            "No swept threshold gave a clean 2-30 cluster split with decent "
            "coverage — extend the sweep range above, or your query mix may be "
            "too small/uniform to cluster meaningfully yet."
        )
    print()


if __name__ == "__main__":
    main()
