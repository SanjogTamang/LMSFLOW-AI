# backend/api/lms_onboard.py
"""FastAPI router for secure SCU LMS onboarding.
It validates credentials via Playwright, encrypts the password, and stores the
encrypted token in the Supabase `users` table.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator
from backend.services.playwright_lms import _login_to_lms, _create_isolated_context
from backend.services.crypto import encrypt
from backend.services.database import get_db, User  # SQLAlchemy model
from sqlalchemy.exc import SQLAlchemyError
from playwright.sync_api import sync_playwright

router = APIRouter()

class OnboardRequest(BaseModel):
    lms_student_id: str = Field(..., min_length=1, description="SCU LMS student ID")
    lms_password: str = Field(..., min_length=1, description="SCU LMS password")

    @validator("lms_student_id", "lms_password")
    def no_whitespace(cls, v):
        if any(ch.isspace() for ch in v):
            raise ValueError("must not contain whitespace")
        return v

@router.post("/api/lms/onboard", status_code=status.HTTP_200_OK)
def onboard_lms(
    payload: OnboardRequest,
    db: get_db = Depends(),
    current_user: User = Depends(),  # existing auth dependency that returns the logged‑in user
):
    """Validate SCU LMS credentials, encrypt the password and persist it.
    Returns a simple JSON success message.
    """
    # 1️⃣ Verify credentials via Playwright (reuse existing login helper)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context, page = _create_isolated_context(browser)
            success = _login_to_lms(page, payload.lms_student_id, payload.lms_password)
            context.close()
            browser.close()
        if not success:
            raise RuntimeError("SCU login failed – check your ID/password.")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"LMS authentication error: {exc}",
        ) from exc

    # 2️⃣ Encrypt the password (never store plain text)
    try:
        encrypted_token = encrypt(payload.lms_password)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Encryption error: {exc}",
        ) from exc

    # 3️⃣ Persist encrypted token to the user record
    try:
        user = db.query(User).filter(User.id == current_user.id).one_or_none()
        if not user:
            raise RuntimeError("Authenticated user not found in DB")
        user.lms_token_enc = encrypted_token
        user.scu_student_id = payload.lms_student_id
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error while saving LMS token: {exc}",
        ) from exc

    return {"detail": "SCU LMS connection established securely"}
