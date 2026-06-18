# app/models/document.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"

    document_id = Column(Integer, primary_key=True, index=True)
    # Document metadata
    document_name = Column(String(255), nullable=False)

    # document_type: POLICY | DIRECTORY | FINANCIAL | CALENDAR | ENROLLMENT
    document_type = Column(String(100), nullable=False)

    # file_path: relative path e.g. uploads/pdf/student_handbook_2026.pdf
    file_path = Column(String(500), nullable=False)

    # upload_size: file size in bytes
    upload_size = Column(Integer, nullable=True)

    # Uploader reference
    uploaded_by_user_id = Column(
        Integer,
        ForeignKey("user_accounts.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Status and versioning
    is_active = Column(Boolean, default=False, nullable=False)
    version = Column(String(50), default="1.0", nullable=False)

    # total_token: populated after preprocessing completes
    total_token = Column(Integer, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # Relationships
    # Many Documents → One UserAccount (admin who uploaded)
    uploaded_by = relationship(
        "UserAccount",
        back_populates="documents",
        foreign_keys=[uploaded_by_user_id]
    )

    # One Document → Many DocumentChunks
    chunks = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<Document id={self.document_id} "
            f"name={self.document_name} "
            f"type={self.document_type} "
            f"active={self.is_active}>"
        )