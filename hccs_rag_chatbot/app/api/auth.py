from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
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


def _issue_token(user: UserAccount) -> str:
    return create_access_token({
        "sub": str(user.user_id),
        "email": user.email,
        "role": user.role.role_name,
    })


@router.get("/login")
def login():
    return RedirectResponse(get_google_auth_url())


@router.get("/callback")
async def callback(code: str, db: Session = Depends(get_db)):
    token_data = await exchange_code_for_token(code)
    user_info = await get_google_user_info(token_data["access_token"])
    email = user_info.get("email")

    if not settings.DEV_MODE and not is_valid_hccs_domain(email):
        db.add(AuthenticationLog(
            event_type="FAILED", timestamp=datetime.utcnow(),
            ip_address="unknown", status="Invalid domain",
        ))
        db.commit()
        return RedirectResponse(f"{FRONTEND_LOGIN}?error=Access+denied")

    ensure_roles(db)
    user = db.query(UserAccount).filter_by(email=email).first()
    if not user:
        student_role = db.query(Role).filter_by(role_name="Student").first()
        user = UserAccount(
            google_id=user_info["sub"],
            email=email,
            display_name=user_info.get("name", email),
            role_id=student_role.role_id,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    user.last_active = datetime.utcnow()
    db.add(AuthenticationLog(
        user_id=user.user_id, event_type="LOGIN",
        timestamp=datetime.utcnow(), status="Success",
    ))
    db.commit()

    token = _issue_token(user)
    # The frontend reads ?token=... off the login page and stores it.
    return RedirectResponse(f"{FRONTEND_LOGIN}?token={token}")


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
    }


@router.post("/logout")
def logout(db: Session = Depends(get_db)):
    return {"message": "Logged out successfully"}
