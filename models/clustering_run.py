# app/models/clustering_run.py

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class ClusteringRun(Base):
    __tablename__ = "clustering_runs"

    run_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Run metadata
    run_timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    total_queries = Column(Integer, nullable=True)
    num_clusters_found = Column(Integer, nullable=True)

    parameters = Column(Text, nullable=True)

    # Trigger reference
    triggered_by_user_id = Column(
        Integer,
        ForeignKey("user_accounts.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Status
    status = Column(String(50), default="RUNNING", nullable=False)

    # Timestamps
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    # Many ClusteringRuns → One UserAccount (admin who triggered, nullable)
    triggered_by = relationship(
        "UserAccount",
        back_populates="clustering_runs",
        foreign_keys=[triggered_by_user_id]
    )

    # One ClusteringRun → Many Clusters
    clusters = relationship(
        "Cluster",
        back_populates="clustering_run",
        cascade="all, delete-orphan"
    )

    # One ClusteringRun → Many QueryLogs
    query_logs = relationship(
        "QueryLog",
        back_populates="clustering_run"
    )

    def __repr__(self):
        return (
            f"<ClusteringRun id={self.run_id} "
            f"status={self.status} "
            f"clusters={self.num_clusters_found}>"
        )