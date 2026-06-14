
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
from app.core.database import Base


class UserAccount(Base):
    __tablename__ = "user_accounts"

    user_id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Google OAuth fields
    google_id = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=False)

    # Role and status
    role_id = Column(
        Integer,
        ForeignKey("roles.role_id", ondelete="RESTRICT"),
        nullable=False
    )
    is_active = Column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_active = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # Relationships
    # Many UserAccounts → One Role
    role = relationship("Role", back_populates="users")

    # One UserAccount → Many AuthenticationLogs
    auth_logs = relationship(
        "AuthenticationLog",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # One UserAccount → Many ChatSessions
    sessions = relationship(
        "ChatSession",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # One UserAccount (admin) → Many Documents uploaded
    documents = relationship(
        "Document",
        back_populates="uploaded_by",
        foreign_keys="Document.uploaded_by_user_id"
    )

    # One UserAccount (admin) → Many ClusteringRuns triggered
    clustering_runs = relationship(
        "ClusteringRun",
        back_populates="triggered_by",
        foreign_keys="ClusteringRun.triggered_by_user_id"
    )

    # One UserAccount (admin) → Many Clusters managed
    managed_clusters = relationship(
        "Cluster",
        back_populates="managed_by",
        foreign_keys="Cluster.managed_by_user_id"
    )

    def __repr__(self):
        return f"<UserAccount id={self.user_id} email={self.email} role_id={self.role_id}>"