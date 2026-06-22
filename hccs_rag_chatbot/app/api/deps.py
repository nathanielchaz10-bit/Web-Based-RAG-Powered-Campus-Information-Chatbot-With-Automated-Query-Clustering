"""Shared API dependencies: auth + role guards.

DEV_MODE behaviour (default on): if a request arrives without a valid token,
the dependency falls back to a seeded local "Head Admin" dev user instead of
rejecting it. This lets the whole app (chat, clustering, dashboards) be exercised
locally without standing up Google OAuth. Set DEV_MODE=False to enforce real
authentication.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import GLOBAL_KEY, global_rate_limiter, rate_limiter
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
            return user
        # Token valid but user gone — fall through to dev/401 handling below.

    if settings.DEV_MODE:
        return get_or_create_dev_user(db)

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


def enforce_chat_rate_limit(user: UserAccount = Depends(get_current_user)) -> UserAccount:
    """Two-layer rate limit for student query submission.

    Wired as a dependency on the chat POST endpoint so it runs BEFORE the
    handler body: a blocked request never invokes the RAG pipeline or any Gemini
    embedding/LLM call. Both layers are checked with allow() first and a slot is
    only spent (record()) once a request clears both, so a request rejected by
    one layer doesn't burn budget in the other.

      * Per-user "front door" -> 429: this user is sending too fast (their fault).
      * Global "back door"    -> 503: the server is at capacity protecting the
        shared Gemini quota (not this user's fault); fail fast with Retry-After
        rather than parking the request, since sync handlers occupy threadpool
        threads while waiting.

    The frontend (api.js / chat.js) surfaces 429 as "Too many requests" and 503
    via the response detail, so no client change is needed.
    """
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


def require_admin(user: UserAccount = Depends(get_current_user)) -> UserAccount:
    """Allow only admin-tier roles."""
    role_name = user.role.role_name if user.role else None
    if role_name not in ADMIN_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
