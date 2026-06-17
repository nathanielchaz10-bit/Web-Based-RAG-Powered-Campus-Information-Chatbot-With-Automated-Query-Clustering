# app/models/auth_log.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base

class AuthenticationLog(Base):
    __tablename__ = "authentication_logs"

    log_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    #  User reference
    user_id = Column(
        Integer,
        ForeignKey("user_accounts.user_id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )

    # Event details
    # event_type: LOGIN | LOGOUT | FAILED | SESSION_EXPIRED
    event_type = Column(String(50), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    ip_address = Column(String(100), nullable=True)

    status = Column(String(100), nullable=False)

    # Relationships
    user = relationship("UserAccount", back_populates="auth_logs")

    def __repr__(self):
        return (
            f"<AuthenticationLog id={self.log_id} "
            f"user_id={self.user_id} event={self.event_type} "
            f"status={self.status}>"
        )