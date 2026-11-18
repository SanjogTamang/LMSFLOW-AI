
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

from backend.services.session_service import (
    create_guest_session,
    get_guest_session,
    delete_guest_session,
)
from backend.services.playwright_lms import (
    verify_lms_credentials,
    discover_student_assignments,
)

router = APIRouter(prefix="/api/guest", tags=["Guest Access"])


class GuestConnectRequest(BaseModel):
    lms_student_id: str = Field(..., min_length=4)
    lms_password: str = Field(..., min_length=1)


def _get_session(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Guest session token required.")

    token = authorization.split(" ", 1)[1]

    try:
        return token, get_guest_session(token)
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc


@router.post("/connect")
def guest_connect(req: GuestConnectRequest):
    is_valid, _, error = verify_lms_credentials(
        req.lms_student_id,
        req.lms_password,
        headless=True,
    )

    if not is_valid:
        raise HTTPException(
            401,
            f"SCU LMS verification failed: {error or 'Invalid credentials'}",
        )

    try:
        session = create_guest_session(
            req.lms_student_id,
            req.lms_password,
        )
        return {
            "message": "SCU LMS connected successfully.",
            **session,
        }
    except Exception as exc:
        raise HTTPException(500, "Could not create guest session.") from exc


@router.get("/assignments")
def guest_assignments(authorization: str = Header(None)):
    _, session = _get_session(authorization)

    try:
        assignments = discover_student_assignments(
            session["lms_student_id"],
            session["lms_password"],
            headless=True,
        )
        return {
            "total": len(assignments),
            "assignments": assignments,
        }
    except Exception as exc:
        raise HTTPException(
            502,
            f"Could not retrieve SCU LMS assignments: {exc}",
        ) from exc


@router.post("/disconnect")
def guest_disconnect(authorization: str = Header(None)):
    token, _ = _get_session(authorization)
    delete_guest_session(token)

    return {"message": "Guest session disconnected."}
