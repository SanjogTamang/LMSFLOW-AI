import uuid
from typing import Optional
from backend.database import get_database
from backend.services.gemini_service import generate_assignment_solution
from backend.services.pdf_service import build_assignment_pdf
from backend.services.playwright_lms import perform_lms_submission
from backend.security import decrypt_credential

# In-memory tracking of active job locks to prevent concurrent runs on the same assignment
active_assignment_locks: set[str] = set()

def update_job_progress(job_id: str, user_id: str, status: str, progress: int, step: str, error: Optional[str] = None):
    """Updates job progress in the database."""
    get_database().update(
        "submission_jobs",
        {"id": job_id, "user_id": user_id},
        {"status": status, "progress_percentage": progress, "current_step": step, "error_message": error},
    )

async def process_full_assignment_job(
    job_id: str,
    user_id: str,
    assignment_id: str,
    course_name: str,
    assignment_title: str,
    instructions: str,
    encrypted_lms_password: Optional[str] = None,
    lms_student_id: Optional[str] = None,
    safe_test_mode: bool = True
):
    """
    Executes the background workflow:
    1. AI draft generation (0 -> 40%)
    2. Save draft record
    3. Generate PDF (40 -> 70%)
    4. Save document record
    5. LMS automated upload/verification (70 -> 100%)
    6. Record audit event
    """
    if assignment_id in active_assignment_locks:
        update_job_progress(job_id, user_id, "failed", 0, "Blocked", "Job already in progress for this assignment.")
        return

    active_assignment_locks.add(assignment_id)
    try:
        # Step 1: AI Generation
        update_job_progress(job_id, user_id, "processing", 15, "Generating assignment solution using Gemini AI...")
        solution_markdown, model_used = generate_assignment_solution(
            course_name=course_name,
            assignment_title=assignment_title,
            instructions=instructions
        )

        # Store Draft
        draft_id = str(uuid.uuid4())
        db = get_database()
        db.insert("assignment_drafts", {
            "id": draft_id, "user_id": user_id, "assignment_id": assignment_id,
            "model_used": model_used, "draft_title": assignment_title,
            "draft_markdown": solution_markdown, "is_student_approved": False,
        })
        db.update("assignments", {"id": assignment_id, "user_id": user_id}, {"current_status": "draft_generated"})

        # Step 2: PDF Generation
        update_job_progress(job_id, user_id, "processing", 50, "Compiling academic PDF using ReportLab...")
        pdf_filename = f"solution_{user_id[:8]}_{assignment_id[:8]}.pdf"
        abs_pdf_path, file_size = build_assignment_pdf(
            course_name=course_name,
            assignment_title=assignment_title,
            solution_markdown=solution_markdown,
            output_filename=pdf_filename,
            student_info=f"Student ID {lms_student_id or 'Verified'}"
        )

        # Store Generated Document
        doc_id = str(uuid.uuid4())
        db.insert("generated_documents", {
            "id": doc_id, "user_id": user_id, "assignment_id": assignment_id,
            "draft_id": draft_id, "filename": pdf_filename, "storage_path": abs_pdf_path,
            "file_size_bytes": file_size, "mime_type": "application/pdf",
        })
        db.update("assignments", {"id": assignment_id, "user_id": user_id}, {"current_status": "pdf_generated"})

        # Step 3: LMS Submission verification if credentials provided
        evidence_file = None
        if lms_student_id and encrypted_lms_password:
            update_job_progress(job_id, user_id, "processing", 75, "Connecting to SCU LMS and preparing document attachment...")
            try:
                plain_password = decrypt_credential(encrypted_lms_password)
                is_success, evidence_file, note = perform_lms_submission(
                    lms_student_id=lms_student_id,
                    lms_password=plain_password,
                    course_name=course_name,
                    assignment_title=assignment_title,
                    pdf_path=abs_pdf_path,
                    safe_test_mode=safe_test_mode,
                    headless=True
                )
                if not is_success:
                    update_job_progress(job_id, user_id, "failed", 75, "LMS attachment failed", note)
                    return
            except Exception as lms_err:
                update_job_progress(job_id, user_id, "failed", 75, "LMS connection error", str(lms_err))
                return

        # Step 4: Record Audit Event
        event_id = str(uuid.uuid4())
        db.insert("submission_events", {
            "id": event_id, "user_id": user_id, "assignment_id": assignment_id,
            "job_id": job_id, "event_type": "workflow_completed",
            "evidence_url": evidence_file or abs_pdf_path,
            "event_details": {"mode": "safe_verified"},
        })
        db.update("assignments", {"id": assignment_id, "user_id": user_id}, {"current_status": "verified"})

        update_job_progress(job_id, user_id, "completed", 100, "Workflow finished successfully. Solution and PDF ready.")
    except Exception as e:
        update_job_progress(job_id, user_id, "failed", 0, "Execution failed", str(e))
    finally:
        active_assignment_locks.discard(assignment_id)

