"""Portal Settings API — admin-only read/write of runtime configuration.

Backs the Portal Settings page. Both routes require an admin-tier role (the
paper's "configurable by the school administrator"); the actual cast/validate/
persist logic lives in ``app.core.settings_store`` so this router stays thin.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core import settings_store
from app.core.database import get_db
from app.models.user_account import UserAccount

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("")
@router.get("/")
def read_settings(
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    """Current effective value of every admin-editable setting."""
    return settings_store.get_effective_settings(db)


@router.put("")
@router.put("/")
def write_settings(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: UserAccount = Depends(require_admin),
):
    """Validate + persist a batch of setting changes; returns the new effective
    values. Live settings (the rate limit) take effect immediately."""
    try:
        return settings_store.update_settings(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
