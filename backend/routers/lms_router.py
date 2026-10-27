import uuid
import datetime
from fastapi import APIRouter, HTTPException, Depends, status
from backend.models import ConnectLMSRequest, LMSConnectionResponse
from backend.database import local_store
from backend.security import get_current_user, AuthenticatedUser, encrypt_credential, decrypt_credential
from backend.services.playwright_lms import verify_lms_credentials

router = APIRouter(prefix="/api/lms", tags=["University LMS Connection"])

@router.post("/connect", response_model=LMSConnectionResponse)
def connect_lms_account(
    req: ConnectLMSRequest,
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Connects the student's personal SCU LMS credentials.
    1. Validates that credentials work on SCU LMS using Playwright.
    2. Encrypts password using AES-256 Fernet.
    3. Saves record linked exclusively to current_user.id.
    """
    # Verify against SCU LMS
    is_valid, current_url, err_msg = verify_lms_credentials(
        lms_student_id=req.lms_student_id,
        lms_password=req.lms_password,
        headless=True
    )

    encrypted_pw = encrypt_credential(req.lms_password)
    status_str = "connected" if is_valid else "failed"
    now_str = datetime.datetime.now().isoformat()

    with local_store.get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM student_lms_connections WHERE user_id = ?",
            (current_user.id,)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE student_lms_connections
                SET lms_student_id = ?, encrypted_lms_password = ?, connection_status = ?, last_verified_at = ?, last_error_message = ?
                WHERE user_id = ?
            """, (req.lms_student_id, encrypted_pw, status_str, now_str, err_msg, current_user.id))
        else:
            conn.execute("""
                INSERT INTO student_lms_connections (id, user_id, lms_student_id, encrypted_lms_password, connection_status, last_verified_at, last_error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (str(uuid.uuid4()), current_user.id, req.lms_student_id, encrypted_pw, status_str, now_str, err_msg))
        
        # Also mark profile as verified if LMS login succeeded
        if is_valid:
            conn.execute("UPDATE profiles SET is_scu_verified = 1, scu_student_id = ? WHERE id = ?", (req.lms_student_id, current_user.id))
        
        conn.commit()

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"SCU LMS verification failed: {err_msg or 'Invalid student ID or password.'}"
        )

    return LMSConnectionResponse(
        user_id=current_user.id,
        lms_student_id=req.lms_student_id,
        connection_status=status_str,
        last_verified_at=now_str,
        last_error_message=err_msg
    )

@router.get("/status", response_model=LMSConnectionResponse)
def get_lms_connection_status(current_user: AuthenticatedUser = Depends(get_current_user)):
    """Returns connection status without returning the student password."""
    with local_store.get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, lms_student_id, connection_status, last_verified_at, last_error_message FROM student_lms_connections WHERE user_id = ?",
            (current_user.id,)
        ).fetchone()

    if not row:
        return LMSConnectionResponse(
            user_id=current_user.id,
            lms_student_id="",
            connection_status="disconnected",
            last_verified_at=None,
            last_error_message=None
        )

    return LMSConnectionResponse(
        user_id=row["user_id"],
        lms_student_id=row["lms_student_id"],
        connection_status=row["connection_status"],
        last_verified_at=row["last_verified_at"],
        last_error_message=row["last_error_message"]
    )

@router.delete("/disconnect")
def disconnect_lms_account(current_user: AuthenticatedUser = Depends(get_current_user)):
    """Purges the student's stored LMS credentials."""
    with local_store.get_conn() as conn:
        conn.execute("DELETE FROM student_lms_connections WHERE user_id = ?", (current_user.id,))
        conn.commit()
    return {"message": "SCU LMS connection disconnected and credentials purged."}

