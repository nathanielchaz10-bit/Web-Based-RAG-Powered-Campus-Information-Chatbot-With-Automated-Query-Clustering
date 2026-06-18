# app/api/clusters.py
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.cluster import Cluster
from app.models.cluster_keyword import ClusterKeyword
from app.models.clustering_run import ClusteringRun
from app.models.query_log import QueryLog
from app.models.user_account import UserAccount

# FIXED IMPORTS: Points straight to your active orchestrator script
from app.services.clustering.pipeline import run_clustering_pipeline

router = APIRouter(prefix="/clusters", tags=["Clusters"])


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
    user: UserAccount = Depends(get_current_user),
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
    user: UserAccount = Depends(get_current_user),
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
