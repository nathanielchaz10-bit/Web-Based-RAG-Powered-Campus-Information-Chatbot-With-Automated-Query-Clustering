"""DB-backed daily usage counts for budget-aware rate limiting.

Counts are derived directly from ``QueryLog`` (one row per completed chat turn),
so they are inherently restart-proof and always consistent with the dashboard —
there's no separate counter table to keep in sync. "Today" is a UTC calendar
day, matching the ``datetime.utcnow()`` timestamps QueryLog stores.

These counts gate the *next* turn (checked before the RAG pipeline runs), so they
reflect turns that have already completed. Under concurrency a small number of
turns may slip in above the cap; that's an acceptable trade for a tight, simple,
restart-proof budget guard with no extra writes on the hot path.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.chat_session import ChatSession
from app.models.query_log import QueryLog


def start_of_utc_day() -> datetime:
    now = datetime.utcnow()
    return datetime(now.year, now.month, now.day)


def global_turns_today(db: Session) -> int:
    """Total chat turns across all students since 00:00 UTC today."""
    return (
        db.query(QueryLog)
        .filter(QueryLog.timestamp >= start_of_utc_day())
        .count()
    )


def user_turns_today(db: Session, user_id: int) -> int:
    """Chat turns by one student since 00:00 UTC today."""
    return (
        db.query(QueryLog)
        .join(ChatSession, QueryLog.session_id == ChatSession.session_id)
        .filter(ChatSession.user_id == user_id)
        .filter(QueryLog.timestamp >= start_of_utc_day())
        .count()
    )
