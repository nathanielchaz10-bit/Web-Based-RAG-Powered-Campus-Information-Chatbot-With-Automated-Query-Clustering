"""Shared API dependencies: auth + role guards.

DEV_MODE behaviour (opt-in; OFF by default): if a request arrives without a valid
token, the dependency falls back to a seeded local "Head Admin" dev user instead
of rejecting it. This lets the whole app (chat, clustering, dashboards) be
exercised locally without standing up Google OAuth. It stays off unless
DEV_MODE=True is set in a local .env, so a public deployment with missing config
fails safe. Real admin access in production comes from BOOTSTRAP_ADMIN_EMAILS.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import (
    GLOBAL_KEY,
    global_rate_limiter,
    guest_daily_rate_limiter,
    guest_rate_limiter,
    rate_limiter,
)
from app.core import usage
from app.core.security import decode_access_token, TokenError
from app.models.role import Role
from app.models.user_account import UserAccount

ADMIN_ROLES = {"Head Admin", "Registrar", "Finance Officer"}

DEFAULT_ROLES = [
    ("Student", "Default role for authenticated students; chatbot access only."),
    ("Head Admin", "Full system access."),
    ("Registrar", "Document Directory, Dashboard, and Query Clusters."),
    ("Finance Officer", "Dashboard and Document Directory (read-only)."),
]

# auto_error=False so missing/invalid headers don't 403 before we can apply the
# DEV_MODE fallback ourselves.
_bearer = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    """Best-effort real visitor IP, used to key the per-guest rate limits.

    The app runs behind a Cloudflare Tunnel (cloudflared -> local uvicorn), so
    ``request.client.host`` is the tunnel's loopback address for EVERY visitor.
    Keying the guest limits on that would collapse them into a single shared
    global bucket (one 5/min + 10/day for the whole world). Cloudflare forwards
    the true client IP in ``CF-Connecting-IP`` (and at the head of
    ``X-Forwarded-For``), so prefer those; fall back to the socket peer for
    direct/local access.

    Note: these headers are only trustworthy because Cloudflare is the sole
    ingress. A client hitting uvicorn directly on the LAN could spoof them to get
    fresh buckets -- bind uvicorn to 127.0.0.1 (tunnel-only) if that matters. The
    server-wide daily cap remains the hard budget backstop regardless.
    """
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # First entry is the original client; the rest are proxy hops.
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def ensure_roles(db: Session) -> None:
    """Seed the four default roles if the table is empty/missing any."""
    existing = {r.role_name for r in db.query(Role).all()}
    created = False
    for name, desc in DEFAULT_ROLES:
        if name not in existing:
            db.add(Role(role_name=name, description=desc))
            created = True
    if created:
        db.commit()


def get_or_create_dev_user(db: Session) -> UserAccount:
    """Return a stable local admin user for DEV_MODE, creating it if needed."""
    ensure_roles(db)
    user = db.query(UserAccount).filter_by(email="dev.admin@hccs.edu.ph").first()
    if user:
        return user
    admin_role = db.query(Role).filter_by(role_name="Head Admin").first()
    user = UserAccount(
        google_id="dev-local-admin",
        email="dev.admin@hccs.edu.ph",
        display_name="Dev Admin",
        role_id=admin_role.role_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> UserAccount:
    """Resolve the authenticated user from a Bearer token.

    Falls back to the dev user in DEV_MODE when no valid token is supplied.
    """
    if credentials and credentials.credentials:
        try:
            payload = decode_access_token(credentials.credentials)
            user_id = int(payload.get("sub"))
        except (TokenError, TypeError, ValueError):
            if settings.DEV_MODE:
                return get_or_create_dev_user(db)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        user = db.query(UserAccount).get(user_id)
        if user:
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This account has been deactivated.",
                )
            return user
        # Token valid but user gone — fall through to dev/401 handling below.

    if settings.DEV_MODE:
        return get_or_create_dev_user(db)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def enforce_chat_rate_limit(
    user: UserAccount = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserAccount:
    """Budget + abuse guard for student query submission.

    Wired as a dependency on the chat POST endpoint so it runs BEFORE the
    handler body: a blocked request never invokes the RAG pipeline or any Gemini
    embedding/LLM call. Checks run cheapest/hardest-ceiling first:

      0. Manual kill switch (CHAT_ENABLED) -> 503: admin paused chat for everyone.
      1. Daily caps (the budget guard for a fixed-dollar Gemini key), counted
         from QueryLog so they survive restarts:
           * Global daily cap   -> 503: the whole server hit today's budget.
           * Per-student daily   -> 429: this student used their daily quota.
      2. Per-minute burst limiters (abuse / quota spikes):
           * Per-user "front door" -> 429: this user is sending too fast.
           * Global "back door"    -> 503: server at per-minute capacity.

    The per-minute layers are checked with allow() first and a slot is only spent
    (record()) once a request clears BOTH, so a request rejected by one layer
    doesn't burn budget in the other. A non-positive cap disables that layer.
    """
    # 0. Manual kill switch — instant, server-wide pause without a restart.
    if not settings.CHAT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is temporarily unavailable. Please check back later.",
        )

    # 1. Daily budget caps. These are the real protection for a small Gemini
    #    budget: per-minute limits cap bursts, but only a daily ceiling caps
    #    cumulative spend over a multi-day run.
    global_daily_max = settings.RATE_LIMIT_GLOBAL_DAILY_MAX
    if global_daily_max > 0 and usage.global_turns_today(db) >= global_daily_max:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant has reached today's usage limit. Please try again tomorrow.",
            headers={"Retry-After": "3600"},
        )

    user_daily_max = settings.RATE_LIMIT_USER_DAILY_MAX
    if user_daily_max > 0 and usage.user_turns_today(db, user.user_id) >= user_daily_max:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You've reached your daily limit of {user_daily_max} questions. Please try again tomorrow.",
            headers={"Retry-After": "3600"},
        )

    # 2. Per-minute burst limiters.
    allowed, retry_after = rate_limiter.allow(user.user_id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded. Please wait a moment before sending another message.",
            headers={"Retry-After": str(retry_after)},
        )

    allowed_global, retry_global = global_rate_limiter.allow(GLOBAL_KEY)
    if not allowed_global:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is busy right now. Please try again in a moment.",
            headers={"Retry-After": str(retry_global)},
        )

    # Admitted by both layers — spend one slot from each budget.
    rate_limiter.record(user.user_id)
    global_rate_limiter.record(GLOBAL_KEY)
    return user


def enforce_guest_rate_limit(
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """Budget + abuse guard for the anonymous guest chat path.

    Guests get their OWN, stricter budget (see RATE_LIMIT_GUEST_* in config):
    a tighter per-minute "front door" and a rolling-24h daily cap, both keyed by
    client IP since guests have no account. On top of that the server-wide
    per-minute back door and daily cap still apply -- guest turns are logged to
    QueryLog, so ``global_turns_today`` counts them toward the Gemini budget.

    All layers are peeked with ``allow()`` first; a slot is only spent
    (``record()``) once the request clears every layer, so a rejection in one
    never burns budget in another.
    """
    if not settings.CHAT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is temporarily unavailable. Please check back later.",
        )

    global_daily_max = settings.RATE_LIMIT_GLOBAL_DAILY_MAX
    if global_daily_max > 0 and usage.global_turns_today(db) >= global_daily_max:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant has reached today's usage limit. Please try again tomorrow.",
            headers={"Retry-After": "3600"},
        )

    ip = client_ip(request)

    # Guest-only daily cap (stricter than the per-student daily cap).
    allowed_daily, retry_daily = guest_daily_rate_limiter.allow(ip)
    if not allowed_daily:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Guests can only ask a limited number of questions per day. "
                   "Please sign in with your @hccs.edu.ph account for full access, "
                   "or try again tomorrow.",
            headers={"Retry-After": str(retry_daily)},
        )

    # Guest-only per-minute front door (stricter than the per-student burst cap).
    allowed, retry_after = guest_rate_limiter.allow(ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You're sending messages too quickly. Please wait a moment before trying again.",
            headers={"Retry-After": str(retry_after)},
        )

    allowed_global, retry_global = global_rate_limiter.allow(GLOBAL_KEY)
    if not allowed_global:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is busy right now. Please try again in a moment.",
            headers={"Retry-After": str(retry_global)},
        )

    guest_daily_rate_limiter.record(ip)
    guest_rate_limiter.record(ip)
    global_rate_limiter.record(GLOBAL_KEY)


def require_admin(user: UserAccount = Depends(get_current_user)) -> UserAccount:
    """Allow only admin-tier roles."""
    role_name = user.role.role_name if user.role else None
    if role_name not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def require_head_admin(user: UserAccount = Depends(get_current_user)) -> UserAccount:
    """Allow only the Head Admin (manages other admin accounts)."""
    role_name = user.role.role_name if user.role else None
    if role_name != "Head Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Head Admin access required",
        )
    return user
