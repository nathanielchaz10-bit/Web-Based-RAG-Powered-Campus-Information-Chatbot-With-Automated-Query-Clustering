"""Admin Management API — back the Portal Settings → Admin Management panel.

Lets the **Head Admin** view, add, edit, and (de)activate administrator
accounts. "Admins" here means ``UserAccount`` rows whose role is one of the
admin tiers (Head Admin / Registrar / Finance Officer); students are not shown.

Adding an admin is a *pre-provision*: because a full account only exists after a
Google sign-in (``google_id`` is required), we create the row keyed by email
with a ``pending:`` placeholder identity. When that person signs in with Google,
the auth callback binds their real Google ID and they inherit the role assigned
here. Until then the row is flagged ``pending`` in the listing.

Deactivation is a soft flag (``is_active``) — never a hard delete, since other
tables (documents, clustering runs, sessions) reference users. ``get_current_user``
enforces the flag, so a deactivated account immediately loses access.

Reads are open to any admin; writes are Head-Admin-only, with guards against
locking everyone out (no deactivating yourself or the last active Head Admin).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import ADMIN_ROLES, require_admin, require_head_admin
from app.core.database import get_db
from app.models.role import Role
from app.models.user_account import UserAccount

router = APIRouter(prefix="/admins", tags=["Admin Management"])

HEAD_ADMIN = "Head Admin"


class AdminOut(BaseModel):
    user_id: int
    display_name: str
    email: str
    role: str
    is_active: bool
    pending: bool  # invited but not yet signed in with Google
    last_active: datetime | None
    created_at: datetime | None
    picture: str | None = None  # Google profile photo; None for pre-provisioned rows


class AdminCreate(BaseModel):
    display_name: str
    email: str
    role: str


class AdminUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = None


class AdminStatus(BaseModel):
    is_active: bool


def _serialize(u: UserAccount) -> AdminOut:
    return AdminOut(
        user_id=u.user_id,
        display_name=u.display_name,
        email=u.email,
        role=u.role.role_name if u.role else "—",
        is_active=u.is_active,
        pending=(u.google_id or "").startswith("pending:"),
        last_active=u.last_active,
        created_at=u.created_at,
        picture=u.picture_url,
    )


def _admin_role_or_400(db: Session, role_name: str) -> Role:
    if role_name not in ADMIN_ROLES:
        raise HTTPException(status_code=400, detail=f"Not an admin role: {role_name!r}")
    role = db.query(Role).filter_by(role_name=role_name).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Unknown role: {role_name!r}")
    return role


def _get_admin_or_404(db: Session, user_id: int) -> UserAccount:
    user = db.query(UserAccount).get(user_id)
    if not user or not user.role or user.role.role_name not in ADMIN_ROLES:
        raise HTTPException(status_code=404, detail="Administrator not found.")
    return user


def _active_head_admins(db: Session, exclude_user_id: int | None = None) -> int:
    """Count active Head Admins, optionally excluding one user — used to stop the
    last Head Admin from being deactivated or demoted (system lockout)."""
    q = (
        db.query(UserAccount)
        .join(Role)
        .filter(Role.role_name == HEAD_ADMIN, UserAccount.is_active.is_(True))
    )
    if exclude_user_id is not None:
        q = q.filter(UserAccount.user_id != exclude_user_id)
    return q.count()


@router.get("", response_model=list[AdminOut])
@router.get("/", response_model=list[AdminOut])
def list_admins(
    db: Session = Depends(get_db),
    _: UserAccount = Depends(require_admin),
):
    """All administrator accounts, oldest first."""
    admins = (
        db.query(UserAccount)
        .join(Role)
        .filter(Role.role_name.in_(ADMIN_ROLES))
        .order_by(UserAccount.created_at.asc())
        .all()
    )
    return [_serialize(u) for u in admins]


@router.post("", response_model=AdminOut, status_code=201)
@router.post("/", response_model=AdminOut, status_code=201)
def add_admin(
    payload: AdminCreate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(require_head_admin),
):
    """Pre-provision a new administrator by email; they inherit the role on their
    first Google sign-in."""
    name = (payload.display_name or "").strip()
    email = (payload.email or "").strip().lower()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    role = _admin_role_or_400(db, payload.role)

    existing = (
        db.query(UserAccount)
        .filter(func.lower(UserAccount.email) == email)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="An account with that email already exists."
        )

    user = UserAccount(
        google_id=f"pending:{email}",
        email=email,
        display_name=name,
        role_id=role.role_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize(user)


@router.put("/{user_id}", response_model=AdminOut)
def update_admin(
    user_id: int,
    payload: AdminUpdate,
    db: Session = Depends(get_db),
    _: UserAccount = Depends(require_head_admin),
):
    """Edit an administrator's display name and/or role."""
    user = _get_admin_or_404(db, user_id)

    if payload.display_name is not None:
        name = payload.display_name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty.")
        user.display_name = name

    if payload.role is not None:
        new_role = _admin_role_or_400(db, payload.role)
        demoting_head = (
            user.role
            and user.role.role_name == HEAD_ADMIN
            and payload.role != HEAD_ADMIN
        )
        if demoting_head and _active_head_admins(db, exclude_user_id=user.user_id) == 0:
            raise HTTPException(
                status_code=400, detail="Cannot remove the last Head Admin."
            )
        user.role_id = new_role.role_id

    db.commit()
    db.refresh(user)
    return _serialize(user)


@router.post("/{user_id}/status", response_model=AdminOut)
def set_admin_status(
    user_id: int,
    payload: AdminStatus,
    db: Session = Depends(get_db),
    current: UserAccount = Depends(require_head_admin),
):
    """Activate or deactivate an administrator account."""
    user = _get_admin_or_404(db, user_id)

    if not payload.is_active:
        if user.user_id == current.user_id:
            raise HTTPException(
                status_code=400, detail="You cannot deactivate your own account."
            )
        if (
            user.role
            and user.role.role_name == HEAD_ADMIN
            and _active_head_admins(db, exclude_user_id=user.user_id) == 0
        ):
            raise HTTPException(
                status_code=400, detail="Cannot deactivate the last Head Admin."
            )

    user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return _serialize(user)
