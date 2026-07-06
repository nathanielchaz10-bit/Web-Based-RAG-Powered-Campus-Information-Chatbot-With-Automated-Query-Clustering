# app/api/clusters.py
from datetime import datetime, timedelta

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.cluster import Cluster
from app.models.cluster_keyword import ClusterKeyword
from app.models.clustering_run import ClusteringRun
from app.models.query_log import QueryLog
from app.models.user_account import UserAccount

# FIXED IMPORTS: Points straight to your active orchestrator script
from app.services.clustering.pipeline import run_clustering_pipeline
from app.services.clustering.vectorizer import deserialize_vector

router = APIRouter(prefix="/clusters", tags=["Clusters"])

# A query whose cosine similarity to its cluster centroid is below this is
# surfaced as "low confidence" in the Raw Queries modal — it sits near the
# edge of the cluster and is the most likely candidate for a mis-grouping.
LOW_CONFIDENCE_THRESHOLD = 0.75


# Map the sentiment labels produced by app/services/nlp/sentiment.py (plus the
# short-form fallbacks) onto the three buckets the clusters page renders.
_POSITIVE_LABELS = {"Positive / Inquisitive", "Positive"}
_URGENT_LABELS = {"Urgent / Frustrated", "Negative"}


def _sentiment_distribution(db: Session):
    """Percentage split of logged-query sentiment, or None if nothing classified."""
    rows = db.query(QueryLog.sentiment).filter(QueryLog.sentiment.isnot(None)).all()
    if not rows:
        return None

    counts = {"positive": 0, "neutral": 0, "urgent": 0}
    for (label,) in rows:
        if label in _POSITIVE_LABELS:
            counts["positive"] += 1
        elif label in _URGENT_LABELS:
            counts["urgent"] += 1
        else:
            counts["neutral"] += 1

    total = sum(counts.values()) or 1
    return {key: round(100 * value / total) for key, value in counts.items()}


def _query_growth_percent(db: Session, now: datetime):
    """Week-over-week growth in logged queries; None when there's no baseline."""
    this_week = db.query(QueryLog).filter(QueryLog.timestamp >= now - timedelta(days=7)).count()
    prev_week = (
        db.query(QueryLog)
        .filter(QueryLog.timestamp >= now - timedelta(days=14))
        .filter(QueryLog.timestamp < now - timedelta(days=7))
        .count()
    )
    if not prev_week:
        return None  # no prior week to compare against -> hide the trend line
    return round(100.0 * (this_week - prev_week) / prev_week, 1)


def _build_overview(db: Session) -> dict:
    """The shape frontend/js/admin/clusters.js expects from both
    GET /clusters/overview and POST /clusters/run."""
    now = datetime.utcnow()

    latest_run = db.query(ClusteringRun).order_by(ClusteringRun.run_id.desc()).first()
    latest_completed = (
        db.query(ClusteringRun)
        .filter_by(status="COMPLETED")
        .order_by(ClusteringRun.run_id.desc())
        .first()
    )

    clusters_payload = []
    if latest_completed:
        clusters = (
            db.query(Cluster)
            .filter_by(clustering_run_id=latest_completed.run_id)
            .order_by(Cluster.query_count.desc())
            .all()
        )
        for c in clusters:
            keywords = (
                db.query(ClusterKeyword)
                .filter_by(cluster_id=c.cluster_id)
                .order_by(ClusterKeyword.frequency.desc())
                .all()
            )
            clusters_payload.append({
                "cluster_id": c.cluster_id,
                "cluster_label": c.cluster_label,
                "cluster_status": c.cluster_status or "ACTIVE",
                "cluster_percentage": c.cluster_percentage or 0,
                "query_count": c.query_count or 0,
                "keywords": [k.keyword for k in keywords],
            })

    return {
        "total_queries": db.query(QueryLog).count(),
        "query_growth_percent": _query_growth_percent(db, now),
        "sentiment": _sentiment_distribution(db),
        "last_run_status": latest_run.status if latest_run else None,
        "clusters": clusters_payload,
    }


@router.get("/overview")
def clusters_overview(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    return _build_overview(db)


@router.post("/run")
def run_clustering_endpoint(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    try:
        run_clustering_pipeline(
            db,
            triggered_by_user_id=user.user_id,
            trigger_source="admin_manual",
        )
    except Exception as exc:
        # The pipeline records expected failures (insufficient data, embedding/
        # ML errors) on the run's status and returns normally; reaching here
        # means something unexpected blew up.
        raise HTTPException(status_code=503, detail=f"Clustering run failed: {exc}")

    # Return the full refreshed overview so the page reflects the just-finished
    # run (clusters, sentiment, status) — not just a bare run summary.
    return _build_overview(db)


@router.get("")
@router.get("/")
def list_clusters(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    latest_run = (
        db.query(ClusteringRun)
        .filter_by(status="COMPLETED")
        .order_by(ClusteringRun.run_id.desc())
        .first()
    )
    if latest_run is None:
        return {"run_id": None, "run_timestamp": None, "total_queries": 0,
                "num_clusters": 0, "clusters": []}

    clusters = (
        db.query(Cluster)
        .filter_by(clustering_run_id=latest_run.run_id)
        .order_by(Cluster.query_count.desc())
        .all()
    )

    payload = []
    for c in clusters:
        keywords = (
            db.query(ClusterKeyword)
            .filter_by(cluster_id=c.cluster_id)
            .order_by(ClusterKeyword.frequency.desc())
            .all()
        )
        payload.append({
            "cluster_id": c.cluster_id,
            "label": c.cluster_label,
            "description": c.cluster_description,
            "query_count": c.query_count,
            "percentage": c.cluster_percentage,
            "keywords": [k.keyword for k in keywords],
        })

    return {
        "run_id": latest_run.run_id,
        "run_timestamp": latest_run.run_timestamp.isoformat() if latest_run.run_timestamp else None,
        "total_queries": latest_run.total_queries,
        "num_clusters": latest_run.num_clusters_found,
        "clusters": payload,
    }


def _cosine_similarity(a, b):
    """Cosine similarity of two vectors, or None if either has zero magnitude."""
    av = np.asarray(a, dtype=float)
    bv = np.asarray(b, dtype=float)
    na = np.linalg.norm(av)
    nb = np.linalg.norm(bv)
    if na == 0 or nb == 0:
        return None
    return float(np.dot(av, bv) / (na * nb))


@router.get("/{cluster_id}/queries")
def cluster_queries(
    cluster_id: int,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    """Raw queries assigned to a cluster, newest first.

    Backs the "View Raw Queries" modal on the Query Clusters page. Each query
    carries a `confidence` (cosine similarity of its stored embedding to the
    cluster centroid, 0-1) so the modal's "Low Confidence Only" toggle has
    something real to filter on. `confidence` is null for queries whose
    embedding wasn't cached (e.g. clustered before query_vector was stored).
    """
    cluster = db.query(Cluster).filter_by(cluster_id=cluster_id).first()
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster not found.")

    centroid = None
    if cluster.centroid_vector:
        try:
            centroid = deserialize_vector(cluster.centroid_vector)
        except Exception:
            centroid = None

    rows = (
        db.query(QueryLog)
        .filter(QueryLog.cluster_id == cluster_id)
        .order_by(QueryLog.timestamp.desc())
        .all()
    )

    queries = []
    for q in rows:
        confidence = None
        if centroid is not None and q.query_vector:
            try:
                sim = _cosine_similarity(deserialize_vector(q.query_vector), centroid)
                if sim is not None:
                    confidence = round(sim, 4)
            except Exception:
                confidence = None

        queries.append({
            "query_id": q.query_id,
            "query_text": q.query_text,
            "timestamp": q.timestamp.isoformat() if q.timestamp else None,
            "sentiment": q.sentiment,
            "detected_intent": q.detected_intent,
            "confidence": confidence,
            "low_confidence": confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD,
        })

    return {
        "cluster_id": cluster.cluster_id,
        "cluster_label": cluster.cluster_label,
        "query_count": len(queries),
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
        "queries": queries,
    }


# Human-readable titles for each sentiment bucket the clusters page renders.
_SENTIMENT_BUCKET_TITLES = {
    "positive": "Positive / Inquisitive",
    "neutral": "Neutral / Transactional",
    "urgent": "Urgent / Frustrated",
}


def _sentiment_bucket_of(label: str) -> str:
    """Map a stored sentiment label onto one of the three dashboard buckets."""
    if label in _POSITIVE_LABELS:
        return "positive"
    if label in _URGENT_LABELS:
        return "urgent"
    return "neutral"


@router.get("/sentiment/{bucket}/queries")
def sentiment_queries(
    bucket: str,
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    """Queries belonging to one sentiment bucket (positive/neutral/urgent).

    Backs the Sentiment Distribution rows on the Query Clusters page: clicking
    a bar lists the student queries classified into that bucket, newest first.
    """
    bucket = bucket.lower()
    if bucket not in _SENTIMENT_BUCKET_TITLES:
        raise HTTPException(status_code=404, detail="Unknown sentiment bucket.")

    rows = (
        db.query(QueryLog)
        .filter(QueryLog.sentiment.isnot(None))
        .order_by(QueryLog.timestamp.desc())
        .all()
    )

    queries = [
        {
            "query_id": q.query_id,
            "query_text": q.query_text,
            "timestamp": q.timestamp.isoformat() if q.timestamp else None,
            "sentiment": q.sentiment,
            "detected_intent": q.detected_intent,
        }
        for q in rows
        if _sentiment_bucket_of(q.sentiment) == bucket
    ]

    return {
        "bucket": bucket,
        "title": _SENTIMENT_BUCKET_TITLES[bucket],
        "query_count": len(queries),
        "queries": queries,
    }
