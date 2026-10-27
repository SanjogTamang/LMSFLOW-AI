import uuid
from typing import List
from fastapi import APIRouter, HTTPException, Depends, status
from backend.models import AssignmentCreateRequest, AssignmentResponse
from backend.database import local_store
from backend.security import get_current_user, AuthenticatedUser, decrypt_credential
from backend.services.playwright_lms import discover_student_assignments

router = APIRouter(prefix="/api/assignments", tags=["Assignments"])

@router.get("", response_model=List[AssignmentResponse])
def list_my_assignments(current_user: AuthenticatedUser = Depends(get_current_user)):
    """
    Returns only assignments owned by the authenticated student.
    Guarantees strict tenant isolation.
    """
    with local_store.get_conn() as conn:
        rows = conn.execute("""
            SELECT id, user_id, course_name, assignment_title, instructions, due_date, submission_format, current_status, created_at
            FROM assignments
            WHERE user_id = ? AND source != 'legacy_demo'
            ORDER BY created_at DESC
        """, (current_user.id,)).fetchall()

    return [
        AssignmentResponse(
            id=r["id"],
            user_id=r["user_id"],
            course_name=r["course_name"],
            assignment_title=r["assignment_title"],
            instructions=r["instructions"] or "",
            due_date=r["due_date"],
            submission_format=r["submission_format"] or "pdf",
            current_status=r["current_status"],
            created_at=r["created_at"]
        ) for r in rows
    ]

@router.post("", response_model=AssignmentResponse)
def create_assignment(
    req: AssignmentCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """Creates a new assignment record under the authenticated student."""
    new_id = str(uuid.uuid4())
    with local_store.get_conn() as conn:
        conn.execute("""
            INSERT INTO assignments (id, user_id, course_name, assignment_title, instructions, due_date, submission_format, lms_assignment_url, current_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'discovered')
        """, (new_id, current_user.id, req.course_name, req.assignment_title, req.instructions, req.due_date, req.submission_format, req.lms_assignment_url))
        conn.commit()

        row = conn.execute("SELECT * FROM assignments WHERE id = ?", (new_id,)).fetchone()

    return AssignmentResponse(
        id=row["id"],
        user_id=row["user_id"],
        course_name=row["course_name"],
        assignment_title=row["assignment_title"],
        instructions=row["instructions"] or "",
        due_date=row["due_date"],
        submission_format=row["submission_format"],
        current_status=row["current_status"],
        created_at=row["created_at"]
    )

@router.post("/sync-lms")
def sync_assignments_from_lms(current_user: AuthenticatedUser = Depends(get_current_user)):
    """
    Connects to SCU LMS using student's stored credentials and discovers new assignments.
    Prevents duplicates on repeated scans.
    """
    with local_store.get_conn() as conn:
        conn_row = conn.execute(
            "SELECT lms_student_id, encrypted_lms_password FROM student_lms_connections WHERE user_id = ? AND connection_status = 'connected'",
            (current_user.id,)
        ).fetchone()

    if not conn_row:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SCU LMS account is not connected. Please connect your credentials first in LMS Settings."
        )

    plain_pw = decrypt_credential(conn_row["encrypted_lms_password"])
    try:
        items = discover_student_assignments(conn_row["lms_student_id"], plain_pw, headless=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not discover assignments from SCU LMS: {exc}",
        ) from exc

    added_count = 0
    with local_store.get_conn() as conn:
        for item in items:
            existing = conn.execute("""
                SELECT id FROM assignments
                WHERE user_id = ? AND (
                    (lms_assignment_url IS NOT NULL AND lms_assignment_url = ?)
                    OR (course_name = ? AND assignment_title = ?)
                )
            """, (
                current_user.id,
                item.get("lms_assignment_url"),
                item["course_name"],
                item["assignment_title"],
            )).fetchone()

            if not existing:
                conn.execute("""
                    INSERT INTO assignments (
                        id, user_id, course_name, assignment_title, instructions,
                        submission_format, lms_assignment_url, current_status, source
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'discovered', 'lms')
                """, (
                    str(uuid.uuid4()),
                    current_user.id,
                    item["course_name"],
                    item["assignment_title"],
                    item["instructions"],
                    item["submission_format"],
                    item.get("lms_assignment_url"),
                ))
                added_count += 1

        conn.commit()

    return {
        "message": (
            f"Sync complete. {added_count} new assignment(s) discovered from SCU LMS."
            if items else
            "Sync completed, but no assignment entries were found on the LMS pages that could be read."
        ),
        "added_count": added_count
    }

@router.get("/{assignment_id}", response_model=AssignmentResponse)
def get_assignment(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    """Fetches assignment details, ensuring the student owns the record."""
    with local_store.get_conn() as conn:
        row = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found.")

    if row["user_id"] != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: You do not own this assignment.")

    return AssignmentResponse(
        id=row["id"],
        user_id=row["user_id"],
        course_name=row["course_name"],
        assignment_title=row["assignment_title"],
        instructions=row["instructions"] or "",
        due_date=row["due_date"],
        submission_format=row["submission_format"],
        current_status=row["current_status"],
        created_at=row["created_at"]
    )
