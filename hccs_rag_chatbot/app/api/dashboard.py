"""Admin dashboard metrics, computed live from the relational schema.

Endpoint shapes match what frontend/js/admin/dashboard.js already expects:
  GET /dashboard/metrics
  GET /dashboard/query-volume
  GET /dashboard/system-health
  GET /dashboard/recent-inquiries
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.chat_response import ChatResponse
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.query_log import QueryLog
from app.models.user_account import UserAccount
from app.services.rag import rag_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_FALLBACK_PHRASES = (
    "i don't know", "i do not know", "don't have information",
    "not in the context", "cannot find",
)


@router.get("/metrics")
def metrics(db: Session = Depends(get_db), _: UserAccount = Depends(require_admin)):
    now = datetime.utcnow()
    total_queries = db.query(QueryLog).count()

    # Week-over-week growth.
    this_week = db.query(QueryLog).filter(QueryLog.timestamp >= now - timedelta(days=7)).count()
    prev_week = (
        db.query(QueryLog)
        .filter(QueryLog.timestamp >= now - timedelta(days=14))
        .filter(QueryLog.timestamp < now - timedelta(days=7))
        .count()
    )
    if prev_week:
        query_growth = round(100.0 * (this_week - prev_week) / prev_week, 1)
    else:
        query_growth = 100.0 if this_week else 0.0

    active_sessions = (
        db.query(ChatSession)
        .filter(ChatSession.last_activity >= now - timedelta(minutes=30))
        .count()
    )

    responses = db.query(ChatResponse.response_text).all()
    if responses:
        good = sum(
            1 for (text,) in responses
            if not any(p in (text or "").lower() for p in _FALLBACK_PHRASES)
        )
        ai_success_rate = round(100.0 * good / len(responses), 1)
    else:
        ai_success_rate = 100.0

    indexed_documents = db.query(Document).count()

    return {
        "total_queries": total_queries,
        "query_growth": query_growth,
        "active_sessions": active_sessions,
        "ai_success_rate": ai_success_rate,
        "indexed_documents": indexed_documents,
    }


@router.get("/query-volume")
def query_volume(db: Session = Depends(get_db), _: UserAccount = Depends(require_admin)):
    today = datetime.utcnow().date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    counts = {d: 0 for d in days}

    window_start = datetime.combine(days[0], datetime.min.time())
    rows = db.query(QueryLog.timestamp).filter(QueryLog.timestamp >= window_start).all()
    for (ts,) in rows:
        d = ts.date()
        if d in counts:
            counts[d] += 1

    values = [counts[d] for d in days]
    peak_day_index = values.index(max(values)) if any(values) else 0
    return {
        # Two-line labels: weekday over its calendar date (e.g. ["Sat", "Jun 14"])
        # so each bar is anchored to a real day rather than a bare weekday name.
        "labels": [[d.strftime("%a"), f"{d.strftime('%b')} {d.day}"] for d in days],
        "values": values,
        "peak_day_index": peak_day_index,
    }


@router.get("/system-health")
def system_health(db: Session = Depends(get_db), _: UserAccount = Depends(require_admin)):
    avg_latency = db.query(QueryLog.response_time_ms).all()
    latencies = [v for (v,) in avg_latency if v is not None]
    avg_latency_ms = int(sum(latencies) / len(latencies)) if latencies else 0

    try:
        import psutil
        memory_usage_percent = round(psutil.virtual_memory().percent, 1)
    except Exception:
        memory_usage_percent = 0.0

    ready = rag_service.is_ready()
    return {
        "vector_index_health": 100 if ready else 0,
        "vector_index_status": "Online" if ready else "Idle",
        "avg_latency_ms": avg_latency_ms,
        "memory_usage_percent": memory_usage_percent,
    }


@router.get("/recent-inquiries")
def recent_inquiries(
    page: int = 1,
    page_size: int = 10,
    q: str = "",
    db: Session = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    """Student inquiries, newest first, paginated.

    Returns {items, total, page, page_size}. The dashboard shows page 1 at
    page_size 10 by default; "View All Activity" pages through the full history
    and passes `q` to search across question text, student email, intent and
    sentiment server-side (so search spans everything, not just one page).
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10

    base = db.query(QueryLog).order_by(QueryLog.query_id.desc())

    term = q.strip()
    if term:
        like = f"%{term}%"
        base = (
            base.outerjoin(ChatSession, QueryLog.session_id == ChatSession.session_id)
            .outerjoin(UserAccount, ChatSession.user_id == UserAccount.user_id)
            .filter(or_(
                QueryLog.query_text.ilike(like),
                QueryLog.detected_intent.ilike(like),
                QueryLog.sentiment.ilike(like),
                UserAccount.email.ilike(like),
            ))
        )

    total = base.count()
    rows = base.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for qr in rows:
        email = "—"
        if qr.session and qr.session.user:
            email = qr.session.user.email
        items.append({
            "timestamp": qr.timestamp.strftime("%Y-%m-%d %H:%M") if qr.timestamp else "",
            "query_text": qr.query_text,
            "user_email": email,
            "intent": qr.detected_intent or "General",
            "sentiment": qr.sentiment or "Neutral",
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}
