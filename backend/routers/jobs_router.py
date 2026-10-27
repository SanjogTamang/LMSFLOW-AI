import uuid
import asyncio
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, status
from backend.models import JobResponse, SubmissionApprovalRequest
from backend.database import local_store
from backend.security import get_current_user, AuthenticatedUser
from backend.worker import process_full_assignment_job, active_assignment_locks

router = APIRouter(prefix="/api", tags=["Background Jobs & Audit Log"])

@router.post("/assignments/{assignment_id}/submit-job", response_model=JobResponse)
def trigger_assignment_job(
    assignment_id: str,
    req: SubmissionApprovalRequest,
    background_tasks: BackgroundTasks,
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """
    Starts an asynchronous background job to generate solution, compile PDF,
    and verify LMS submission.
    Requires explicit student approval (`confirm_submission: True`).
    """
    if not req.confirm_submission:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Student approval is mandatory prior to initiating submission operations."
        )

    # Check lock to prevent duplicate runs
    if assignment_id in active_assignment_locks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An automation job is already running for this assignment."
        )

    with local_store.get_conn() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not assignment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found.")
        if assignment["user_id"] != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

        conn_row = conn.execute(
            "SELECT lms_student_id, encrypted_lms_password FROM student_lms_connections WHERE user_id = ?",
            (current_user.id,)
        ).fetchone()

    job_id = str(uuid.uuid4())
    with local_store.get_conn() as conn:
        conn.execute("""
            INSERT INTO submission_jobs (id, user_id, assignment_id, job_type, status, progress_percentage, current_step)
            VALUES (?, ?, ?, 'auto_process', 'pending', 0, 'Job queued in background')
        """, (job_id, current_user.id, assignment_id))
        conn.commit()

    # Dispatch to background task worker
    background_tasks.add_task(
        process_full_assignment_job,
        job_id=job_id,
        user_id=current_user.id,
        assignment_id=assignment_id,
        course_name=assignment["course_name"],
        assignment_title=assignment["assignment_title"],
        instructions=assignment["instructions"] or "",
        encrypted_lms_password=conn_row["encrypted_lms_password"] if conn_row else None,
        lms_student_id=conn_row["lms_student_id"] if conn_row else None,
        safe_test_mode=True
    )

    return JobResponse(
        id=job_id,
        user_id=current_user.id,
        assignment_id=assignment_id,
        job_type="auto_process",
        status="pending",
        progress_percentage=0,
        current_step="Job queued in background"
    )

@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_status(job_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    """Polls real-time progress of a running job."""
    with local_store.get_conn() as conn:
        row = conn.execute("SELECT * FROM submission_jobs WHERE id = ?", (job_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if row["user_id"] != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    return JobResponse(
        id=row["id"],
        user_id=row["user_id"],
        assignment_id=row["assignment_id"],
        job_type=row["job_type"],
        status=row["status"],
        progress_percentage=row["progress_percentage"],
        current_step=row["current_step"],
        error_message=row["error_message"],
        created_at=row["created_at"]
    )

@router.get("/audit-events")
def list_student_audit_events(current_user: AuthenticatedUser = Depends(get_current_user)):
    """Returns the immutable audit log for the authenticated student."""
    with local_store.get_conn() as conn:
        rows = conn.execute("""
            SELECT id, user_id, assignment_id, job_id, event_type, evidence_url, event_details, created_at
            FROM submission_events
            WHERE user_id = ?
            ORDER BY created_at DESC
        """, (current_user.id,)).fetchall()

    return [dict(r) for r in rows]

