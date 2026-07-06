import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import ADMIN_ROLES, ensure_roles, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
# NOTE: the module is google_auth.py (the original import said "google_oauth",
# which does not exist and broke the whole auth router on import).
from app.services.auth.google_auth import (
    get_google_auth_url,
    exchange_code_for_token,
    get_google_user_info,
)
from app.services.auth.domain_validator import is_valid_hccs_domain
from app.models.user_account import UserAccount
from app.models.auth_log import AuthenticationLog
from app.models.role import Role

router = APIRouter(prefix="/auth", tags=["Authentication"])

FRONTEND_LOGIN = "/frontend/index.html"

# Name of the short-lived cookie that ties a login redirect to its callback
# (OAuth CSRF / "login CSRF" guard).
_STATE_COOKIE = "oauth_state"


def _cookies_secure() -> bool:
    """Mark auth cookies Secure only when we're actually on https (the tunnel).

    On plain http://localhost a Secure cookie may be dropped, which would break
    local dev, so we key it off the configured redirect URI's scheme.
    """
    return settings.GOOGLE_REDIRECT_URI.lower().startswith("https")


def _issue_token(user: UserAccount) -> str:
    return create_access_token({
        "sub": str(user.user_id),
        "email": user.email,
        "role": user.role.role_name,
    })


@router.get("/config")
def public_config():
    """Public, unauthenticated flags the login page needs *before* sign-in.

    Only DEV_MODE is exposed, so the frontend can hide the dev-login bypass when
    the server isn't in dev mode. Safe to expose: in production it's just False,
    and the /dev-login endpoint itself is already gated on DEV_MODE server-side.
    """
    return {"dev_mode": settings.DEV_MODE}


@router.get("/login")
def login():
    # Mint a one-time state, hand it to Google, and stash it in a short-lived
    # cookie so the callback can confirm the response belongs to a flow THIS
    # browser started (defends against login-CSRF / forged callbacks).
    state = secrets.token_urlsafe(32)
    resp = RedirectResponse(get_google_auth_url(state))
    resp.set_cookie(
        _STATE_COOKIE, state,
        max_age=600, httponly=True, secure=_cookies_secure(),
        samesite="lax", path="/",
    )
    return resp


@router.get("/callback")
async def callback(
    request: Request,
    code: str,
    state: str | None = None,
    db: Session = Depends(get_db),
):
    # Verify the state echoed by Google matches the cookie we set in /login.
    cookie_state = request.cookies.get(_STATE_COOKIE)
    if not cookie_state or not state or not secrets.compare_digest(cookie_state, state):
        resp = RedirectResponse(f"{FRONTEND_LOGIN}?error=Invalid+login+state.+Please+try+again.")
        resp.delete_cookie(_STATE_COOKIE, path="/")
        return resp

    token_data = await exchange_code_for_token(code)
    user_info = await get_google_user_info(token_data["access_token"])
    email = user_info.get("email")
    # Google returns email_verified as a JSON boolean; str() also handles the
    # rare string form ("true"), and a missing key safely becomes False.
    email_verified = str(user_info.get("email_verified")).lower() == "true"

    # Developer/owner allowlist (settings.BOOTSTRAP_ADMIN_EMAILS): these emails may
    # sign in even off the school domain and are provisioned as Head Admin below.
    # This is how the maintainers administer a DEV_MODE=False deployment.
    is_bootstrap_admin = bool(email) and email.lower() in settings.bootstrap_admin_emails

    # School-only gate. Because the app is published as External, Google lets ANY
    # account reach this callback, so this is the sole wall: accept only a VERIFIED
    # email that is on the school domain OR on the developer allowlist. (Skipped in
    # DEV_MODE for local testing.)
    if not settings.DEV_MODE and not (
        email_verified and (is_valid_hccs_domain(email) or is_bootstrap_admin)
    ):
        db.add(AuthenticationLog(
            event_type="FAILED", timestamp=datetime.utcnow(),
            ip_address="unknown", status="Invalid domain",
        ))
        db.commit()
        return RedirectResponse(f"{FRONTEND_LOGIN}?error=Access+denied")

    ensure_roles(db)
    user = db.query(UserAccount).filter_by(email=email).first()
    if not user:
        # Allowlisted developers bootstrap straight to Head Admin; everyone else
        # starts as a Student.
        default_role = "Head Admin" if is_bootstrap_admin else "Student"
        role_row = db.query(Role).filter_by(role_name=default_role).first()
        user = UserAccount(
            google_id=user_info["sub"],
            email=email,
            display_name=user_info.get("name", email),
            role_id=role_row.role_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # A Head Admin can deactivate accounts; block their sign-in here too.
        if not user.is_active:
            db.add(AuthenticationLog(
                user_id=user.user_id, event_type="FAILED",
                timestamp=datetime.utcnow(), status="Account deactivated",
            ))
            db.commit()
            return RedirectResponse(f"{FRONTEND_LOGIN}?error=Account+deactivated")
        # A pre-provisioned ("invited") admin signs in for the first time: bind
        # their real Google identity, keeping the role the Head Admin assigned.
        if (user.google_id or "").startswith("pending:"):
            user.google_id = user_info["sub"]
            user.display_name = user_info.get("name", user.display_name)
        # Keep allowlisted developers at Head Admin even if their row predates the
        # allowlist (e.g. it was created as a Student on an earlier sign-in).
        if is_bootstrap_admin and (not user.role or user.role.role_name != "Head Admin"):
            head_role = db.query(Role).filter_by(role_name="Head Admin").first()
            if head_role:
                user.role_id = head_role.role_id

    # Refresh the Google profile photo on every sign-in (it can change, and this
    # backfills accounts created before the column existed).
    user.picture_url = user_info.get("picture")
    user.last_active = datetime.utcnow()
    db.add(AuthenticationLog(
        user_id=user.user_id, event_type="LOGIN",
        timestamp=datetime.utcnow(), status="Success",
    ))
    db.commit()

    token = _issue_token(user)
    # Return the token in the URL *fragment* (#token=...), not the query string:
    # fragments are never sent to the server, so the token can't leak into access
    # logs, Referer headers, or proxies. auth.js reads it from location.hash and
    # immediately strips it from the address bar. Clear the one-time state cookie.
    resp = RedirectResponse(f"{FRONTEND_LOGIN}#token={token}")
    resp.delete_cookie(_STATE_COOKIE, path="/")
    return resp


@router.get("/dev-login")
def dev_login(
    role: str = Query("Head Admin"),
    db: Session = Depends(get_db),
):
    """DEV_MODE only: mint a token for a seeded user of the given role, so the
    app can be tested end-to-end without configuring Google OAuth."""
    if not settings.DEV_MODE:
        raise HTTPException(status_code=403, detail="Dev login is disabled.")

    valid_roles = {"Student"} | ADMIN_ROLES
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Unknown role: {role}")

    ensure_roles(db)
    slug = role.lower().replace(" ", ".")
    email = f"dev.{slug}@hccs.edu.ph"
    user = db.query(UserAccount).filter_by(email=email).first()
    if not user:
        role_row = db.query(Role).filter_by(role_name=role).first()
        user = UserAccount(
            google_id=f"dev-local-{slug}",
            email=email,
            display_name=f"Dev {role}",
            role_id=role_row.role_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    return {
        "access_token": _issue_token(user),
        "token_type": "bearer",
        "user": {
            "user_id": user.user_id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role.role_name,
        },
    }


@router.get("/me")
def me(user: UserAccount = Depends(get_current_user)):
    return {
        "user_id": user.user_id,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role.role_name if user.role else None,
        "picture": user.picture_url,
    }


@router.post("/logout")
def logout(db: Session = Depends(get_db)):
    return {"message": "Logged out successfully"}
