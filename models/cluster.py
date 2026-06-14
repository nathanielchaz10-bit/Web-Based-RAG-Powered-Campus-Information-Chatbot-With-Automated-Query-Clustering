# app/models/cluster.py

from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class Cluster(Base):
    __tablename__ = "clusters"

    cluster_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    #  Cluster identity
    cluster_label = Column(String(255), nullable=False)
    cluster_description = Column(Text, nullable=True)

    centroid_vector = Column(Text, nullable=True)

    # Statistics
    query_count = Column(Integer, default=0, nullable=False)
    cluster_percentage = Column(Float, nullable=True)

    # Statu
    cluster_status = Column(String(50), default="ACTIVE", nullable=False)

    # Foreign keys
    clustering_run_id = Column(
        Integer,
        ForeignKey("clustering_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    managed_by_user_id = Column(
        Integer,
        ForeignKey("user_accounts.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    # Many Clusters → One ClusteringRun
    clustering_run = relationship("ClusteringRun", back_populates="clusters")

    # Many Clusters → One UserAccount (admin who manages it)
    managed_by = relationship(
        "UserAccount",
        back_populates="managed_clusters",
        foreign_keys=[managed_by_user_id]
    )

    # One Cluster → Many ClusterKeywords
    keywords = relationship(
        "ClusterKeyword",
        back_populates="cluster",
        cascade="all, delete-orphan"
    )

    # One Cluster → Many QueryLogs
    query_logs = relationship(
        "QueryLog",
        back_populates="cluster"
    )

    def __repr__(self):
        return (
            f"<Cluster id={self.cluster_id} "
            f"label={self.cluster_label} "
            f"queries={self.query_count} "
            f"pct={self.cluster_percentage}>"
        )