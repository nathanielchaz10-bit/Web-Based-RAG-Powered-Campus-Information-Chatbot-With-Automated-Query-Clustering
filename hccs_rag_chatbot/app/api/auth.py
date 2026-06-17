from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import create_access_token
from app.services.auth.google_oauth import (
    get_google_auth_url,
    exchange_code_for_token,
    get_google_user_info
)
from app.services.auth.domain_validator import is_valid_hccs_domain
from app.models.user_account import UserAccount
from app.models.auth_log import AuthenticationLog
from app.models.role import Role
from datetime import datetime

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.get("/login")
def login():
    return RedirectResponse(get_google_auth_url())

@router.get("/callback")
async def callback(code: str, db: Session = Depends(get_db)):
    token_data = await exchange_code_for_token(code)
    user_info = await get_google_user_info(token_data["access_token"])
    email = user_info.get("email")

    if not is_valid_hccs_domain(email):
        log = AuthenticationLog(
            event_type="FAILED",
            timestamp=datetime.utcnow(),
            ip_address="unknown",
            status="Invalid domain"
        )
        db.add(log)
        db.commit()
        raise HTTPException(status_code=403, detail="Access denied")

    user = db.query(UserAccount).filter_by(email=email).first()
    if not user:
        student_role = db.query(Role).filter_by(role_name="Student").first()
        user = UserAccount(
            google_id=user_info["sub"],
            email=email,
            display_name=user_info.get("name", email),
            role_id=student_role.role_id
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    user.last_active = datetime.utcnow()
    log = AuthenticationLog(
        user_id=user.user_id,
        event_type="LOGIN",
        timestamp=datetime.utcnow(),
        status="Success"
    )
    db.add(log)
    db.commit()

    token = create_access_token({
        "sub": str(user.user_id),
        "email": user.email,
        "role": user.role.role_name
    })
    return {"access_token": token, "token_type": "bearer"}

@router.post("/logout")
def logout(db: Session = Depends(get_db)):
    return {"message": "Logged out successfully"}