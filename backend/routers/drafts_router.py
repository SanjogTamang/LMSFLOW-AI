import uuid
import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from backend.models import GenerateDraftRequest, UpdateDraftRequest, DraftResponse
from backend.database import local_store
from backend.security import get_current_user, AuthenticatedUser
from backend.services.gemini_service import generate_assignment_solution

router = APIRouter(prefix="/api/assignments", tags=["Assignment Drafts"])

@router.post("/{assignment_id}/generate-draft", response_model=DraftResponse)
def create_ai_draft(
    assignment_id: str,
    req: GenerateDraftRequest,
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """Generates an academic solution draft using Gemini AI for the student's assignment."""
    with local_store.get_conn() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()

    if not assignment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found.")

    if assignment["user_id"] != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied: You do not own this assignment.")

    # Call Gemini AI
    solution_md, model_name = generate_assignment_solution(
        course_name=assignment["course_name"],
        assignment_title=assignment["assignment_title"],
        instructions=assignment["instructions"] or "",
        student_notes=req.custom_instructions
    )

    draft_id = str(uuid.uuid4())
    now_str = datetime.datetime.now().isoformat()

    with local_store.get_conn() as conn:
        conn.execute("""
            INSERT INTO assignment_drafts (id, user_id, assignment_id, model_used, draft_title, draft_markdown, is_student_approved, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """, (draft_id, current_user.id, assignment_id, model_name, assignment["assignment_title"], solution_md, now_str))
        conn.execute("UPDATE assignments SET current_status = 'draft_generated' WHERE id = ?", (assignment_id,))
        conn.commit()

    return DraftResponse(
        id=draft_id,
        user_id=current_user.id,
        assignment_id=assignment_id,
        model_used=model_name,
        draft_title=assignment["assignment_title"],
        draft_markdown=solution_md,
        is_student_approved=False,
        created_at=now_str
    )

@router.get("/{assignment_id}/draft", response_model=Optional[DraftResponse])
def get_latest_draft(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    """Retrieves the latest draft for this assignment."""
    with local_store.get_conn() as conn:
        assignment = conn.execute("SELECT user_id FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
        if not assignment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found.")
        if assignment["user_id"] != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

        draft = conn.execute("""
            SELECT * FROM assignment_drafts
            WHERE assignment_id = ? AND user_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (assignment_id, current_user.id)).fetchone()

    if not draft:
        return None

    return DraftResponse(
        id=draft["id"],
        user_id=draft["user_id"],
        assignment_id=draft["assignment_id"],
        model_used=draft["model_used"],
        draft_title=draft["draft_title"],
        draft_markdown=draft["draft_markdown"],
        is_student_approved=bool(draft["is_student_approved"]),
        approved_at=draft["approved_at"],
        created_at=draft["created_at"]
    )

@router.put("/{assignment_id}/draft", response_model=DraftResponse)
def update_draft(
    assignment_id: str,
    req: UpdateDraftRequest,
    current_user: AuthenticatedUser = Depends(get_current_user)
):
    """Allows the student to review, refine, and edit their AI draft."""
    with local_store.get_conn() as conn:
        draft = conn.execute("""
            SELECT * FROM assignment_drafts
            WHERE assignment_id = ? AND user_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (assignment_id, current_user.id)).fetchone()

        if not draft:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existing draft to update.")

        conn.execute("""
            UPDATE assignment_drafts
            SET draft_markdown = ?, draft_title = COALESCE(?, draft_title)
            WHERE id = ?
        """, (req.draft_markdown, req.draft_title, draft["id"]))
        conn.commit()

        updated = conn.execute("SELECT * FROM assignment_drafts WHERE id = ?", (draft["id"],)).fetchone()

    return DraftResponse(
        id=updated["id"],
        user_id=updated["user_id"],
        assignment_id=updated["assignment_id"],
        model_used=updated["model_used"],
        draft_title=updated["draft_title"],
        draft_markdown=updated["draft_markdown"],
        is_student_approved=bool(updated["is_student_approved"]),
        approved_at=updated["approved_at"],
        created_at=updated["created_at"]
    )

@router.post("/{assignment_id}/approve")
def approve_draft(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    """Student marks draft as approved for PDF generation & LMS submission."""
    now_str = datetime.datetime.now().isoformat()
    with local_store.get_conn() as conn:
        draft = conn.execute("""
            SELECT id FROM assignment_drafts
            WHERE assignment_id = ? AND user_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (assignment_id, current_user.id)).fetchone()

        if not draft:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No draft found to approve.")

        conn.execute("""
            UPDATE assignment_drafts SET is_student_approved = 1, approved_at = ? WHERE id = ?
        """, (now_str, draft["id"]))
        conn.execute("UPDATE assignments SET current_status = 'approved' WHERE id = ?", (assignment_id,))
        conn.commit()

    return {"message": "Draft approved by student.", "approved_at": now_str}

