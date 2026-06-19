# app/services/clustering/pipeline.py
"""
Orchestrates one full clustering run, matching the SOP2 flowchart end to end:

  Create ClusteringRun record
    -> Fetch unclustered queries -> (fetch error? -> Failed Extraction)
    -> Enough queries? (>= CLUSTERING_MIN_QUERIES) -> (no -> Insufficient)
    -> Preprocess + Semantic Vectorization (embed)
    -> Execute ML Clustering Algorithm (Agglomerative)
    -> ML execution successful? -> (no -> Failed ML)
    -> Generate cluster metadata + keywords (LLM labeler)
    -> Store cluster results (Cluster, ClusterKeyword)
    -> Update QueryLog.cluster_id records
    -> Update ClusteringRun status = COMPLETED
    -> (Dashboard/SystemMetrics pick this up on next read; no push needed)

This module owns all database writes for a run. vectorizer/algorithm/labeler
are pure functions with no DB access, which keeps them independently testable.
"""
import json
import numpy as np
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

# Side effect: bridges GEMINI_API_KEY -> GOOGLE_API_KEY so the Gemini clients
# built lazily by the vectorizer/labeler authenticate. The chat path gets this
# via rag_service; the clustering path (scheduler/admin trigger) never imports
# rag_service, so it must bridge the key here -- otherwise a .env with only
# GEMINI_API_KEY set would fail clustering even though chat works.
import app.services._engine_bootstrap  # noqa: F401

from app.models.clustering_run import ClusteringRun
from app.models.cluster import Cluster
from app.models.cluster_keyword import ClusterKeyword
from app.models.query_log import QueryLog

from app.services.clustering.preprocessor import (
    fetch_clusterable_queries,
    InsufficientQueriesError,
    QueryFetchError,
)
from app.services.clustering.vectorizer import embed_queries, serialize_vector
from app.services.clustering.algorithm import run_agglomerative_clustering, compute_centroid
from app.services.clustering.labeler import label_clusters


# ── Status constants ─────────────────────────────────────────────────────
# Kept as plain strings (matching ClusteringRun.status's String(50) column)
# rather than a SQLAlchemy enum, since the column was modeled as free-text
# in the ERD and other code already writes status="RUNNING" by default.
STATUS_RUNNING = "RUNNING"
STATUS_COMPLETED = "COMPLETED"
STATUS_FAILED_EXTRACTION = "FAILED_EXTRACTION"
STATUS_INSUFFICIENT = "INSUFFICIENT"
STATUS_FAILED_ML = "FAILED_ML"


def run_clustering_pipeline(
    db: Session,
    triggered_by_user_id: Optional[int] = None,
    trigger_source: str = "scheduler",
) -> ClusteringRun:
    """
    Executes one complete clustering run and persists the result.

    Args:
        db: active SQLAlchemy session.
        triggered_by_user_id: admin UserAccount.user_id if manually triggered,
            None if triggered by the scheduler.
        trigger_source: free-text note on what initiated the run (e.g.
            "scheduler", "admin_manual") — informational only, stored in
            ClusteringRun.parameters alongside the other run parameters.

    Returns:
        The completed (or failed/insufficient) ClusteringRun row. The run's
        `status` field tells the caller (scheduler.py or the admin-trigger
        API endpoint) what happened — this function never raises for
        *expected* failure paths (insufficient data, embedding/clustering
        errors); it only raises if creating/committing the ClusteringRun
        record itself fails, since at that point there's nothing left to
        update.
    """
    # Note: ClusteringRun has no dedicated trigger_source column in the
    # current schema -- only triggered_by_user_id (nullable FK, NULL means
    # scheduler-triggered). trigger_source is recorded inside `parameters`
    # (JSON) instead, alongside the other run metadata written at the end.
    run = ClusteringRun(
        run_timestamp=datetime.utcnow(),
        triggered_by_user_id=triggered_by_user_id,
        status=STATUS_RUNNING,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # ── 1. Fetch + validate query count ────────────────────────────────
    try:
        records = fetch_clusterable_queries(db)
    except QueryFetchError as exc:
        return _fail_run(db, run, STATUS_FAILED_EXTRACTION, total_queries=None, error=str(exc))
    except InsufficientQueriesError as exc:
        return _fail_run(db, run, STATUS_INSUFFICIENT, total_queries=exc.found, error=str(exc))

    run.total_queries = len(records)
    db.commit()

    texts_by_id = {r.query_id: r.query_text for r in records}
    query_ids = [r.query_id for r in records]
    query_texts = [r.query_text for r in records]

    # ── 2. Embed (Semantic Vectorization) ──────────────────────────────
    try:
        embedded = embed_queries(query_ids, query_texts)
    except Exception as exc:
        return _fail_run(db, run, STATUS_FAILED_ML, total_queries=len(records), error=f"Embedding failed: {exc}")

    if not embedded:
        return _fail_run(db, run, STATUS_FAILED_ML, total_queries=len(records), error="Embedding returned no vectors.")

    embedded_ids = [qid for qid, _ in embedded]
    vectors = np.array([vec for _, vec in embedded])

    # Persist embeddings to QueryLog.query_vector regardless of clustering
    # outcome below -- this is useful cached work even if the ML step itself
    # later fails, and matches "Store Raw Query" / query_vector in the ERD.
    for qid, vec in embedded:
        db.query(QueryLog).filter(QueryLog.query_id == qid).update(
            {"query_vector": serialize_vector(vec)}
        )
    db.commit()

    # ── 3. Execute ML Clustering Algorithm (Agglomerative) ─────────────
    try:
        groups = run_agglomerative_clustering(embedded_ids, vectors)
    except Exception as exc:
        return _fail_run(db, run, STATUS_FAILED_ML, total_queries=len(records), error=f"Clustering failed: {exc}")

    if not groups:
        # Not an error -- just means no group met MIN_CLUSTER_SIZE this run.
        # Still a "successful" run; it simply found zero stable topics.
        run.num_clusters_found = 0
        run.status = STATUS_COMPLETED
        run.completed_at = datetime.utcnow()
        run.parameters = json.dumps({"trigger_source": trigger_source, "clusters_found": 0})
        db.commit()
        db.refresh(run)
        return run

    # ── 4. Generate cluster metadata + keywords (LLM labeler) ──────────
    try:
        labels = label_clusters(groups, texts_by_id)
    except Exception as exc:
        return _fail_run(db, run, STATUS_FAILED_ML, total_queries=len(records), error=f"Labeling failed: {exc}")

    # ── 5. Store cluster results ────────────────────────────────────────
    # Full rebuild semantics (per design decision): clear this run's slate
    # of cluster assignments before writing new ones. We don't delete prior
    # Cluster rows from earlier ClusteringRuns -- each run gets its own set
    # of Cluster rows (clustering_run_id FK), so historical dashboards for
    # past runs remain intact. Only QueryLog.cluster_id (which always points
    # at the *latest* clustering of that query) is overwritten.
    vector_lookup = dict(zip(embedded_ids, vectors))
    total_clustered_queries = sum(len(qids) for qids in groups.values())

    for label, member_query_ids in groups.items():
        meta = labels.get(label, {"name": "Unlabeled Cluster", "description": "", "keywords": []})
        member_vectors = np.array([vector_lookup[qid] for qid in member_query_ids])
        centroid = compute_centroid(member_vectors)

        cluster = Cluster(
            cluster_label=meta["name"],
            cluster_description=meta.get("description"),
            centroid_vector=serialize_vector(centroid.tolist()),
            query_count=len(member_query_ids),
            cluster_percentage=round(100 * len(member_query_ids) / total_clustered_queries, 2),
            cluster_status="ACTIVE",
            clustering_run_id=run.run_id,
            is_active=True,
        )
        db.add(cluster)
        db.commit()
        db.refresh(cluster)

        member_texts_lower = [texts_by_id[qid].lower() for qid in member_query_ids if qid in texts_by_id]

        for kw in meta.get("keywords", []):
            keyword_lower = kw["keyword"].lower()
            # Literal substring count across this cluster's queries. Approximate
            # (no stemming/tokenization) but gives a real, non-zero frequency
            # signal for the dashboard rather than a meaningless placeholder.
            frequency = sum(1 for text in member_texts_lower if keyword_lower in text)

            db.add(ClusterKeyword(
                cluster_id=cluster.cluster_id,
                keyword=kw["keyword"],
                frequency=frequency,
                relevance_score=kw.get("relevance_score"),
            ))

        db.query(QueryLog).filter(QueryLog.query_id.in_(member_query_ids)).update(
            {"cluster_id": cluster.cluster_id, "clustering_run_id": run.run_id},
            synchronize_session=False,
        )

    db.commit()

    # ── 6. Update ClusteringRun status = COMPLETED ─────────────────────
    run.num_clusters_found = len(groups)
    run.status = STATUS_COMPLETED
    run.completed_at = datetime.utcnow()
    run.parameters = json.dumps({
        "trigger_source": trigger_source,
        "clusters_found": len(groups),
        "queries_clustered": total_clustered_queries,
        "queries_left_unclustered": len(records) - total_clustered_queries,
    })
    db.commit()
    db.refresh(run)

    return run


def _fail_run(
    db: Session,
    run: ClusteringRun,
    status: str,
    total_queries: Optional[int],
    error: str,
) -> ClusteringRun:
    """Shared terminal-failure path: log the error, update run status, commit."""
    print(f"[clustering pipeline] Run {run.run_id} failed: {status} — {error}")
    run.status = status
    run.total_queries = total_queries
    run.completed_at = datetime.utcnow()
    run.parameters = json.dumps({"error": error})
    db.commit()
    db.refresh(run)
    return run