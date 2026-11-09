import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from backend.database import get_database
from backend.models import AssignmentCreateRequest, AssignmentResponse
from backend.security import AuthenticatedUser, decrypt_credential, get_current_user
from backend.services.playwright_lms import discover_student_assignments

router = APIRouter(prefix="/api/assignments", tags=["Assignments"])


def _response(row: dict) -> AssignmentResponse:
    return AssignmentResponse(
        id=row["id"], user_id=row["user_id"], course_name=row["course_name"],
        assignment_title=row["assignment_title"], instructions=row.get("instructions") or "",
        due_date=row.get("due_date"), submission_format=row.get("submission_format") or "pdf",
        current_status=row["current_status"], created_at=row.get("created_at"),
    )


@router.get("", response_model=List[AssignmentResponse])
def list_my_assignments(current_user: AuthenticatedUser = Depends(get_current_user)):
    rows = get_database().select("assignments", {"user_id": current_user.id})
    return [_response(row) for row in rows if row.get("source") != "legacy_demo"]


@router.post("", response_model=AssignmentResponse)
def create_assignment(req: AssignmentCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    row = get_database().insert("assignments", {
        "id": str(uuid.uuid4()), "user_id": current_user.id,
        "course_name": req.course_name, "assignment_title": req.assignment_title,
        "instructions": req.instructions, "due_date": req.due_date,
        "submission_format": req.submission_format, "lms_assignment_url": req.lms_assignment_url,
        "current_status": "discovered", "source": "manual",
    })
    return _response(row)


@router.post("/sync-lms")
def sync_assignments_from_lms(current_user: AuthenticatedUser = Depends(get_current_user)):
    db = get_database()
    connection = db.select("student_lms_connections", {
        "user_id": current_user.id, "connection_status": "connected"
    }, single=True)
    if not connection:
        raise HTTPException(400, "SCU LMS account is not connected. Please connect your credentials first.")

    try:
        items = discover_student_assignments(
            connection["lms_student_id"], decrypt_credential(connection["encrypted_lms_password"]), headless=True
        )
    except Exception as exc:
        raise HTTPException(502, f"Could not discover assignments from SCU LMS: {exc}") from exc

    added_count = 0
    for item in items:
        existing = db.select("assignments", {"user_id": current_user.id, "course_name": item["course_name"]})
        duplicate = any(row["assignment_title"] == item["assignment_title"] for row in existing)
        url = item.get("lms_assignment_url")
        duplicate = duplicate or bool(url and any(row.get("lms_assignment_url") == url for row in existing))
        if not duplicate:
            db.insert("assignments", {
                "id": str(uuid.uuid4()), "user_id": current_user.id,
                "course_name": item["course_name"], "assignment_title": item["assignment_title"],
                "instructions": item["instructions"], "submission_format": item["submission_format"],
                "lms_assignment_url": url, "current_status": "discovered", "source": "lms",
            })
            added_count += 1
    return {
        "message": f"Sync complete. {added_count} new assignment(s) discovered from SCU LMS." if items else "Sync completed with no readable assignments.",
        "added_count": added_count,
    }


@router.get("/{assignment_id}", response_model=AssignmentResponse)
def get_assignment(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    row = get_database().select("assignments", {"id": assignment_id, "user_id": current_user.id}, single=True)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    return _response(row)
