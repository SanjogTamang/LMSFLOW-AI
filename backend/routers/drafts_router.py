import datetime
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_database
from backend.models import DraftResponse, GenerateDraftRequest, UpdateDraftRequest
from backend.security import AuthenticatedUser, get_current_user
from backend.services.gemini_service import generate_assignment_solution

router = APIRouter(prefix="/api/assignments", tags=["Assignment Drafts"])

def _draft(row: dict) -> DraftResponse:
    return DraftResponse(
        id=row["id"], user_id=row["user_id"], assignment_id=row["assignment_id"],
        model_used=row["model_used"], draft_title=row.get("draft_title"), draft_markdown=row["draft_markdown"],
        is_student_approved=bool(row.get("is_student_approved", False)), approved_at=row.get("approved_at"),
        created_at=row.get("created_at"),
    )


def _owned_assignment(db, assignment_id: str, user_id: str):
    row = db.select("assignments", {"id": assignment_id, "user_id": user_id}, single=True)
    if not row:
        raise HTTPException(404, "Assignment not found")
    return row


def _latest_draft(db, assignment_id: str, user_id: str):
    rows = db.select("assignment_drafts", {"assignment_id": assignment_id, "user_id": user_id})
    return max(rows, key=lambda row: row.get("created_at") or "", default=None)


@router.post("/{assignment_id}/generate-draft", response_model=DraftResponse)
def create_ai_draft(assignment_id: str, req: GenerateDraftRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    db = get_database()
    assignment = _owned_assignment(db, assignment_id, current_user.id)
    solution_md, model_name = generate_assignment_solution(
        course_name=assignment["course_name"], assignment_title=assignment["assignment_title"],
        instructions=assignment.get("instructions") or "", student_notes=req.custom_instructions,
    )
    row = db.insert("assignment_drafts", {
        "id": str(uuid.uuid4()), "user_id": current_user.id, "assignment_id": assignment_id,
        "model_used": model_name, "draft_title": assignment["assignment_title"], "draft_markdown": solution_md,
        "is_student_approved": False,
    })
    db.update("assignments", {"id": assignment_id, "user_id": current_user.id}, {"current_status": "draft_generated"})
    return _draft(row)


@router.get("/{assignment_id}/draft", response_model=Optional[DraftResponse])
def get_latest_draft(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    db = get_database()
    _owned_assignment(db, assignment_id, current_user.id)
    row = _latest_draft(db, assignment_id, current_user.id)
    return _draft(row) if row else None


@router.put("/{assignment_id}/draft", response_model=DraftResponse)
def update_draft(assignment_id: str, req: UpdateDraftRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    db = get_database()
    draft = _latest_draft(db, assignment_id, current_user.id)
    if not draft:
        raise HTTPException(404, "No existing draft to update")
    values = {"draft_markdown": req.draft_markdown}
    if req.draft_title is not None:
        values["draft_title"] = req.draft_title
    db.update("assignment_drafts", {"id": draft["id"], "user_id": current_user.id}, values)
    updated = db.select("assignment_drafts", {"id": draft["id"], "user_id": current_user.id}, single=True)
    return _draft(updated)


@router.post("/{assignment_id}/approve")
def approve_draft(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    db = get_database()
    draft = _latest_draft(db, assignment_id, current_user.id)
    if not draft:
        raise HTTPException(404, "No draft found to approve")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    db.update("assignment_drafts", {"id": draft["id"], "user_id": current_user.id}, {
        "is_student_approved": True, "approved_at": now,
    })
    db.update("assignments", {"id": assignment_id, "user_id": current_user.id}, {"current_status": "approved"})
    return {"message": "Draft approved by student.", "approved_at": now}

