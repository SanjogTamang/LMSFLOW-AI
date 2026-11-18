
import uuid
from typing import Optional

from backend.database import get_database
from backend.services.gemini_service import generate_assignment_solution
from backend.services.pdf_service import build_assignment_pdf


# Prevent concurrent jobs for the same assignment.
active_assignment_locks: set[str] = set()


def update_job_progress(
    job_id: str,
    user_id: str,
    status: str,
    progress: int,
    step: str,
    error: Optional[str] = None,
):
    """Update background job progress in the database."""
    get_database().update(
        "submission_jobs",
        {"id": job_id, "user_id": user_id},
        {
            "status": status,
            "progress_percentage": progress,
            "current_step": step,
            "error_message": error,
        },
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
    safe_test_mode: bool = True,
):
    """
    Generate and save an assignment draft and PDF.

    LMS submission is intentionally handled separately,
    after the student reviews and approves the draft.
    """

    if assignment_id in active_assignment_locks:
        update_job_progress(
            job_id,
            user_id,
            "failed",
            0,
            "Blocked",
            "Job already in progress for this assignment.",
        )
        return

    active_assignment_locks.add(assignment_id)

    try:
        # Step 1: Generate assignment solution.
        update_job_progress(
            job_id,
            user_id,
            "processing",
            15,
            "Generating assignment solution using Gemini AI...",
        )

        solution_markdown, model_used = generate_assignment_solution(
            course_name=course_name,
            assignment_title=assignment_title,
            instructions=instructions,
        )

        db = get_database()

        # Step 2: Save draft.
        draft_id = str(uuid.uuid4())

        db.insert(
            "assignment_drafts",
            {
                "id": draft_id,
                "user_id": user_id,
                "assignment_id": assignment_id,
                "model_used": model_used,
                "draft_title": assignment_title,
                "draft_markdown": solution_markdown,
                "is_student_approved": False,
            },
        )

        db.update(
            "assignments",
            {"id": assignment_id, "user_id": user_id},
            {"current_status": "draft_generated"},
        )

        # Step 3: Generate PDF.
        update_job_progress(
            job_id,
            user_id,
            "processing",
            50,
            "Compiling academic PDF using ReportLab...",
        )

        pdf_filename = (
            f"solution_{user_id[:8]}_{assignment_id[:8]}.pdf"
        )

        abs_pdf_path, file_size = build_assignment_pdf(
            course_name=course_name,
            assignment_title=assignment_title,
            solution_markdown=solution_markdown,
            output_filename=pdf_filename,
            student_info=f"Student ID {lms_student_id or 'Verified'}",
        )

        # Step 4: Save generated document.
        doc_id = str(uuid.uuid4())

        db.insert(
            "generated_documents",
            {
                "id": doc_id,
                "user_id": user_id,
                "assignment_id": assignment_id,
                "draft_id": draft_id,
                "filename": pdf_filename,
                "storage_path": abs_pdf_path,
                "file_size_bytes": file_size,
                "mime_type": "application/pdf",
            },
        )

        db.update(
            "assignments",
            {"id": assignment_id, "user_id": user_id},
            {"current_status": "pdf_generated"},
        )

        # Step 5: Record draft-generation event.
        event_id = str(uuid.uuid4())

        db.insert(
            "submission_events",
            {
                "id": event_id,
                "user_id": user_id,
                "assignment_id": assignment_id,
                "job_id": job_id,
                "event_type": "workflow_completed",
                "evidence_url": abs_pdf_path,
                "event_details": {
                    "mode": "draft_only",
                    "lms_submission": "not_attempted",
                    "student_approval_required": True,
                },
            },
        )

        # Step 6: Finish draft-generation job.
        update_job_progress(
            job_id,
            user_id,
            "completed",
            100,
            "Draft and PDF generated successfully. Waiting for student review and approval.",
        )

    except Exception as e:
        update_job_progress(
            job_id,
            user_id,
            "failed",
            0,
            "Execution failed",
            str(e),
        )

    finally:
        active_assignment_locks.discard(assignment_id)
