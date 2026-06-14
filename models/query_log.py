# app/models/query_log.py

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class QueryLog(Base):
    __tablename__ = "query_logs"

    query_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Query content
    query_text = Column(Text, nullable=False)
    query_vector = Column(Text, nullable=True)

    # Timestamps
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Session reference
    session_id = Column(
        Integer,
        ForeignKey("chat_sessions.session_id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Cluster assignment
    cluster_id = Column(
        Integer,
        ForeignKey("clusters.cluster_id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    clustering_run_id = Column(
        Integer,
        ForeignKey("clustering_runs.run_id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Quality and validation flags
    is_valid = Column(Boolean, default=True, nullable=False)

    # Performance metrics
    response_time_ms = Column(Integer, nullable=True)

    # NLP enrichmennt
    sentiment = Column(String(50), nullable=True)

    detected_intent = Column(String(100), nullable=True)

    # Relationships
    # Many QueryLogs → One ChatSession
    session = relationship("ChatSession", back_populates="queries")

    # Many QueryLogs → One Cluster (nullable until clustered)
    cluster = relationship("Cluster", back_populates="query_logs")

    # Many QueryLogs → One ClusteringRun (nullable until clustered)
    clustering_run = relationship("ClusteringRun", back_populates="query_logs")

    # One QueryLog → One ChatResponse
    response = relationship(
        "ChatResponse",
        back_populates="query",
        uselist=False,
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<QueryLog id={self.query_id} "
            f"session_id={self.session_id} "
            f"intent={self.detected_intent} "
            f"sentiment={self.sentiment} "
            f"cluster_id={self.cluster_id}>"
        )