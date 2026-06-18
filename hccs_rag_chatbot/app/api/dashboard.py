"""Admin dashboard metrics, computed live from the relational schema.

Endpoint shapes match what frontend/js/admin/dashboard.js already expects:
  GET /dashboard/metrics
  GET /dashboard/query-volume
  GET /dashboard/system-health
  GET /dashboard/recent-inquiries
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
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
        "labels": [d.strftime("%a") for d in days],
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
def recent_inquiries(db: Session = Depends(get_db), _: UserAccount = Depends(require_admin)):
    rows = (
        db.query(QueryLog)
        .order_by(QueryLog.query_id.desc())
        .limit(10)
        .all()
    )
    out = []
    for q in rows:
        email = "—"
        if q.session and q.session.user:
            email = q.session.user.email
        out.append({
            "timestamp": q.timestamp.strftime("%Y-%m-%d %H:%M") if q.timestamp else "",
            "query_text": q.query_text,
            "user_email": email,
            "intent": q.detected_intent or "General",
            "sentiment": q.sentiment or "Neutral",
        })
    return out
