import datetime
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from backend.database import get_database
from backend.models import ConnectLMSRequest, LMSConnectionResponse
from backend.security import get_current_user, AuthenticatedUser, encrypt_credential, decrypt_credential
from backend.services.playwright_lms import verify_lms_credentials

router = APIRouter(prefix="/api/lms", tags=["University LMS Connection"])

@router.post("/connect", response_model=LMSConnectionResponse)
def connect_lms_account(req: ConnectLMSRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    is_valid, _, err_msg = verify_lms_credentials(
        lms_student_id=req.lms_student_id, lms_password=req.lms_password, headless=True
    )
    db = get_database()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    values = {
        "user_id": current_user.id, "lms_student_id": req.lms_student_id,
        "encrypted_lms_password": encrypt_credential(req.lms_password),
        "connection_status": "connected" if is_valid else "failed",
        "last_verified_at": now, "last_error_message": err_msg,
    }
    existing = db.select("student_lms_connections", {"user_id": current_user.id}, single=True)
    if existing:
        db.update("student_lms_connections", {"id": existing["id"], "user_id": current_user.id}, values)
    else:
        values["id"] = str(uuid.uuid4())
        db.insert("student_lms_connections", values)
    if is_valid:
        db.update("profiles", {"id": current_user.id}, {"is_scu_verified": True, "scu_student_id": req.lms_student_id})
    if not is_valid:
        raise HTTPException(400, f"SCU LMS verification failed: {err_msg or 'Invalid credentials'}")
    return LMSConnectionResponse(user_id=current_user.id, lms_student_id=req.lms_student_id,
                                 connection_status="connected", last_verified_at=now, last_error_message=err_msg)


@router.get("/status", response_model=LMSConnectionResponse)
def get_lms_connection_status(current_user: AuthenticatedUser = Depends(get_current_user)):
    row = get_database().select("student_lms_connections", {"user_id": current_user.id}, single=True)
    if not row:
        return LMSConnectionResponse(user_id=current_user.id, lms_student_id="", connection_status="disconnected")
    return LMSConnectionResponse(user_id=row["user_id"], lms_student_id=row["lms_student_id"],
                                 connection_status=row["connection_status"], last_verified_at=row.get("last_verified_at"),
                                 last_error_message=row.get("last_error_message"))


@router.delete("/disconnect")
def disconnect_lms_account(current_user: AuthenticatedUser = Depends(get_current_user)):
    get_database().delete("student_lms_connections", {"user_id": current_user.id})
    return {"message": "SCU LMS connection disconnected and credentials purged."}

