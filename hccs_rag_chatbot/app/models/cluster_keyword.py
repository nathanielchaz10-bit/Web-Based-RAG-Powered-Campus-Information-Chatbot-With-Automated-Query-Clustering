# app/models/cluster_keyword.py

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class ClusterKeyword(Base):
    __tablename__ = "cluster_keywords"

    keyword_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Parent cluster reference
    cluster_id = Column(
        Integer,
        ForeignKey("clusters.cluster_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Keyword data
    keyword = Column(String(255), nullable=False)
    frequency = Column(Integer, default=0, nullable=False)
    relevance_score = Column(Float, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    # Many ClusterKeywords → One Cluster
    cluster = relationship("Cluster", back_populates="keywords")

    def __repr__(self):
        return (
            f"<ClusterKeyword id={self.keyword_id} "
            f"cluster_id={self.cluster_id} "
            f"keyword={self.keyword} "
            f"score={self.relevance_score}>"
        )