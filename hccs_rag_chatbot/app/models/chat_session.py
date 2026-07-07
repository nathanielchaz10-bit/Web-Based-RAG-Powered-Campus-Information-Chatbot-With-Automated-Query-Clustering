# app/models/chat_session.py

from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # User reference
    user_id = Column(
        Integer,
        ForeignKey("user_accounts.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Session metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_activity = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )
    total_messages = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    # Relationships
    # Many ChatSessions → One UserAccount
    user = relationship("UserAccount", back_populates="sessions")

    # One ChatSession → Many QueryLogs.
    # No delete cascade on purpose: deleting a session NULLs its queries'
    # session_id (FK is nullable, ondelete=SET NULL) instead of deleting them, so
    # the QueryLog rows survive for admin dashboards / query clustering when a
    # student clears their chat history.
    # ponytail: relies on SQLAlchemy's default FK-nullify on parent delete — no
    # per-endpoint code needed.
    queries = relationship("QueryLog", back_populates="session")

    def __repr__(self):
        return (
            f"<ChatSession id={self.session_id} "
            f"user_id={self.user_id} "
            f"messages={self.total_messages} "
            f"active={self.is_active}>"
        )