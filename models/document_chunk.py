from sqlalchemy import Column, Integer, String, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    # Following ERD:
    chunk_id = Column(Integer, primary_key=True, index=True)

    document_id = Column(Integer, ForeignKey("documents.document_id"), nullable=False)

    chunk_text = Column(Text, nullable=False)
    vector_id = Column(String, nullable=False)
    page_number = Column(Integer, nullable=True)
    section_title = Column(String, nullable=True)
    chunk_metadata = Column("metadata", JSON, nullable=True)

    document = relationship("Document", back_populates="chunks")