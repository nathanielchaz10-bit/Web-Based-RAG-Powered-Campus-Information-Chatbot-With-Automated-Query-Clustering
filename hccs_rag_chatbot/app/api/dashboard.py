"""Admin dashboard metrics, computed live from the relational schema.

Endpoint shapes match what frontend/js/admin/dashboard.js already expects:
  GET /dashboard/metrics
  GET /dashboard/query-volume
  GET /dashboard/system-health
  GET /dashboard/recent-inquiries
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.config import settings
from app.core.database import get_db
from app.core import usage
from app.core.rate_limit import GLOBAL_KEY, global_rate_limiter
from app.models.chat_response import ChatResponse
from app.models.chat_session import ChatSession
from app.models.document import Document
from app.models.query_log import QueryLog
from app.models.user_account import UserAccount
from app.services.rag import rag_service

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Timestamps are stored as naive UTC (datetime.utcnow); render them in the
# school's local time. ponytail: fixed +8 — Philippines has no DST; swap for
# zoneinfo("Asia/Manila") if the school ever moves timezone.
PH_TZ = timezone(timedelta(hours=8))


def _to_ph(dt):
    """Naive-UTC datetime -> Philippine local time (UTC+8)."""
    return dt.replace(tzinfo=timezone.utc).astimezone(PH_TZ)


_FALLBACK_PHRASES = (
    "i don't know", "i do not know", "don't have information",
    "not in the context", "cannot find",
)


def _is_answered(text, is_fallback) -> bool:
    """Whether a chat response counts as a success (the assistant answered).

    Prefers the stored ``is_fallback`` flag, set at generation time from the
    NO_ANSWER sentinel. Legacy rows written before that flag existed have
    ``is_fallback IS NULL``; for those we fall back to the old phrase heuristic
    on the response text.
    """
    if is_fallback is not None:
        return not is_fallback
    return not any(p in (text or "").lower() for p in _FALLBACK_PHRASES)


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

    # Windowed to the last 7 days so this tracks *recent* performance, like the
    # other live cards, instead of an all-time average that barely moves. A
    # response "succeeds" when it isn't one of the canned can't-answer fallbacks.
    recent_responses = (
        db.query(ChatResponse.response_text, ChatResponse.is_fallback)
        .filter(ChatResponse.generated_at >= now - timedelta(days=7))
        .all()
    )
    if recent_responses:
        good = sum(
            1 for (text, is_fb) in recent_responses
            if _is_answered(text, is_fb)
        )
        ai_success_rate = round(100.0 * good / len(recent_responses), 1)
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

    # Latency trend: average response time per day across the last 7 days, so an
    # admin can see whether the chatbot is getting slower over time (the paper's
    # "response efficiency over time"). Built straight from QueryLog, which
    # already persists every turn's latency + timestamp -- no separate metrics
    # sampler needed. Days with no traffic stay None so the chart skips them.
    today = datetime.utcnow().date()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    sums = {d: 0 for d in days}
    counts = {d: 0 for d in days}
    window_start = datetime.combine(days[0], datetime.min.time())
    trend_rows = (
        db.query(QueryLog.timestamp, QueryLog.response_time_ms)
        .filter(QueryLog.timestamp >= window_start)
        .filter(QueryLog.response_time_ms.isnot(None))
        .all()
    )
    for ts, ms in trend_rows:
        d = ts.date()
        if d in counts:
            sums[d] += ms
            counts[d] += 1
    trend_values = [round(sums[d] / counts[d]) if counts[d] else None for d in days]

    try:
        import psutil
        memory_usage_percent = round(psutil.virtual_memory().percent, 1)
    except Exception:
        memory_usage_percent = 0.0

    ready = rag_service.is_ready()

    # Gemini rate-limit headroom: how much of the global per-window turn budget
    # is currently spent. Because each chat turn fans out into a fixed number of
    # Gemini calls, this global limiter IS the Gemini-quota guard -- so its usage
    # is the earliest warning that the bot is about to start rejecting students
    # (HTTP 429). Read without spending a slot.
    used, gmax, gwindow = global_rate_limiter.usage(GLOBAL_KEY)
    if gmax <= 0:
        gemini_headroom = {
            "enabled": False, "used": 0, "max": 0,
            "percent": 0.0, "window_seconds": gwindow, "status": "Disabled",
        }
    else:
        percent = round(100.0 * used / gmax, 1)
        status = "Healthy" if percent < 70 else ("Busy" if percent < 100 else "Saturated")
        gemini_headroom = {
            "enabled": True, "used": used, "max": gmax,
            "percent": percent, "window_seconds": gwindow, "status": status,
        }

    # Daily budget: how much of today's server-wide turn cap is spent. This is
    # the cumulative-spend guard for the fixed Gemini key (the per-minute
    # headroom above only reflects bursts). Counted from QueryLog so it's
    # restart-proof. Also reports the manual kill switch state.
    g_daily_max = settings.RATE_LIMIT_GLOBAL_DAILY_MAX
    used_today = usage.global_turns_today(db)
    if g_daily_max <= 0:
        daily_budget = {
            "enabled": False, "used": used_today, "max": 0,
            "percent": 0.0, "status": "Disabled",
        }
    else:
        d_percent = round(100.0 * used_today / g_daily_max, 1)
        d_status = "Healthy" if d_percent < 70 else ("Low" if d_percent < 100 else "Exhausted")
        daily_budget = {
            "enabled": True, "used": used_today, "max": g_daily_max,
            "percent": d_percent, "status": d_status,
        }

    return {
        "vector_index_health": 100 if ready else 0,
        "vector_index_status": "Online" if ready else "Idle",
        "avg_latency_ms": avg_latency_ms,
        "memory_usage_percent": memory_usage_percent,
        "latency_trend": {
            "labels": [[d.strftime("%a"), f"{d.strftime('%b')} {d.day}"] for d in days],
            "values": trend_values,
        },
        "gemini_headroom": gemini_headroom,
        "daily_budget": daily_budget,
        "chat_enabled": settings.CHAT_ENABLED,
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
        conds = [
            QueryLog.query_text.ilike(like),
            QueryLog.detected_intent.ilike(like),
            QueryLog.sentiment.ilike(like),
            UserAccount.email.ilike(like),
        ]
        # Let admins find guest inquiries by typing "guest".
        if term.lower() in "guest":
            conds.append(QueryLog.is_guest.is_(True))
        base = (
            base.outerjoin(ChatSession, QueryLog.session_id == ChatSession.session_id)
            .outerjoin(UserAccount, ChatSession.user_id == UserAccount.user_id)
            .filter(or_(*conds))
        )

    total = base.count()
    rows = base.offset((page - 1) * page_size).limit(page_size).all()

    items = []
    for qr in rows:
        if qr.is_guest:
            email = "Guest"
        elif qr.session and qr.session.user:
            email = qr.session.user.email
        else:
            email = "—"
        items.append({
            "timestamp": _to_ph(qr.timestamp).strftime("%Y-%m-%d %I:%M %p") if qr.timestamp else "",
            "query_text": qr.query_text,
            "user_email": email,
            "is_guest": bool(qr.is_guest),
            "intent": qr.detected_intent or "General Inquiry",
            "sentiment": qr.sentiment or "Neutral",
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}
