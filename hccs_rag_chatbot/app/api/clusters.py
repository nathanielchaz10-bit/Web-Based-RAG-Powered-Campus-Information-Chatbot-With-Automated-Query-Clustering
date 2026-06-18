"""Query-cluster endpoints.

  POST /clusters/run  (admin)  -> run the LLM-clustering engine over QueryLog,
                                  persisting a new ClusteringRun + Clusters.
  GET  /clusters               -> the clusters from the most recent completed
                                  run, shaped for the admin Query Clusters page.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.models.cluster import Cluster
from app.models.cluster_keyword import ClusterKeyword
from app.models.clustering_run import ClusteringRun
from app.models.user_account import UserAccount
from app.services.clustering import clustering_service

router = APIRouter(prefix="/clusters", tags=["Clusters"])


@router.post("/run")
def run_clustering_endpoint(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    try:
        summary = clustering_service.run_clustering(db, triggered_by_user_id=user.user_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Clustering failed: {exc}")
    return summary


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
