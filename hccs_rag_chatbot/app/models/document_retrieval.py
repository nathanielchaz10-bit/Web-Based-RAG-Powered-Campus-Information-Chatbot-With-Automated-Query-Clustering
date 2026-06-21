# app/models/document_retrieval.py

from sqlalchemy import Column, Integer, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base


class DocumentRetrieval(Base):
    """One row per (answered query, document) where the document's chunks were
    retrieved to help answer a student's question.

    This is the raw event log behind the admin Document Directory's
    "N retrievals this month" activity metric: counting rows per document in a
    time window gives usage, and comparing windows gives the trend. Kept as
    timestamped events (rather than a running counter on documents) precisely so
    "this month vs last month" can be computed.
    """

    __tablename__ = "document_retrievals"

    retrieval_id = Column(Integer, primary_key=True, index=True)
    document_id = Column(
        Integer,
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    retrieved_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    document = relationship("Document", back_populates="retrievals")

    # Composite index for the per-document, per-window COUNT(*) the directory runs.
    __table_args__ = (
        Index("ix_doc_retrieval_doc_time", "document_id", "retrieved_at"),
    )

    def __repr__(self):
        return (
            f"<DocumentRetrieval id={self.retrieval_id} "
            f"document_id={self.document_id} at={self.retrieved_at}>"
        )
