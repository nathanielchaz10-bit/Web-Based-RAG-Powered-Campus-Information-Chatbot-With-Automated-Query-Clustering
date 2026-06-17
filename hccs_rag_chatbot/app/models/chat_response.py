# app/models/chat_response.py

from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class ChatResponse(Base):
    __tablename__ = "chat_responses"

    response_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Parent query reference
    query_id = Column(
        Integer,
        ForeignKey("query_logs.query_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True
    )

    # Response content
    response_text = Column(Text, nullable=False)
    source_chunks = Column(Text, nullable=True)

    # Quality metrics
    confidence_score = Column(Float, nullable=True)

    tokens_used = Column(Integer, nullable=True)

    # Timestamps
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # User feedback
    was_helpful = Column(Boolean, nullable=True)

    # Relationships
    query = relationship("QueryLog", back_populates="response")

    def __repr__(self):
        return (
            f"<ChatResponse id={self.response_id} "
            f"query_id={self.query_id} "
            f"confidence={self.confidence_score} "
            f"tokens={self.tokens_used}>"
        )