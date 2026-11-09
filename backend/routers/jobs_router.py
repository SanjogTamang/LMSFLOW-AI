import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from backend.database import get_database
from backend.models import JobResponse, SubmissionApprovalRequest
from backend.security import get_current_user, AuthenticatedUser
from backend.worker import process_full_assignment_job, active_assignment_locks

router = APIRouter(prefix="/api", tags=["Background Jobs & Audit Log"])

@router.post("/assignments/{assignment_id}/submit-job", response_model=JobResponse)
def trigger_assignment_job(assignment_id: str, req: SubmissionApprovalRequest,
                          background_tasks: BackgroundTasks,
                          current_user: AuthenticatedUser = Depends(get_current_user)):
    if not req.confirm_submission:
        raise HTTPException(400, "Student approval is mandatory prior to submission operations")
    if assignment_id in active_assignment_locks:
        raise HTTPException(409, "An automation job is already running for this assignment")

    db = get_database()
    assignment = db.select("assignments", {"id": assignment_id, "user_id": current_user.id}, single=True)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    connection = db.select("student_lms_connections", {"user_id": current_user.id}, single=True)
    job_id = str(uuid.uuid4())
    db.insert("submission_jobs", {
        "id": job_id, "user_id": current_user.id, "assignment_id": assignment_id,
        "job_type": "submit_assignment", "status": "pending", "progress_percentage": 0,
        "current_step": "Job queued in background",
    })
    background_tasks.add_task(
        process_full_assignment_job, job_id=job_id, user_id=current_user.id,
        assignment_id=assignment_id, course_name=assignment["course_name"],
        assignment_title=assignment["assignment_title"], instructions=assignment.get("instructions") or "",
        encrypted_lms_password=connection.get("encrypted_lms_password") if connection else None,
        lms_student_id=connection.get("lms_student_id") if connection else None,
        safe_test_mode=True,
    )
    return JobResponse(id=job_id, user_id=current_user.id, assignment_id=assignment_id,
                       job_type="submit_assignment", status="pending", progress_percentage=0,
                       current_step="Job queued in background")


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job_status(job_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    row = get_database().select("submission_jobs", {"id": job_id, "user_id": current_user.id}, single=True)
    if not row:
        raise HTTPException(404, "Job not found")
    return JobResponse(id=row["id"], user_id=row["user_id"], assignment_id=row["assignment_id"],
                       job_type=row["job_type"], status=row["status"], progress_percentage=row["progress_percentage"],
                       current_step=row.get("current_step"), error_message=row.get("error_message"), created_at=row.get("created_at"))


@router.get("/audit-events")
def list_student_audit_events(current_user: AuthenticatedUser = Depends(get_current_user)):
    rows = get_database().select("submission_events", {"user_id": current_user.id})
    return sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)

