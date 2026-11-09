import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from backend.database import get_database
from backend.models import DocumentResponse
from backend.security import get_current_user, AuthenticatedUser
from backend.services.pdf_service import build_assignment_pdf
from backend.services.storage_service import get_authorized_document_path

router = APIRouter(prefix="/api/assignments", tags=["Documents & PDFs"])

def _latest(db, table: str, filters: dict):
    rows = db.select(table, filters)
    return max(rows, key=lambda row: row.get("created_at") or "", default=None)


@router.post("/{assignment_id}/generate-pdf", response_model=DocumentResponse)
def generate_pdf_document(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    db = get_database()
    assignment = db.select("assignments", {"id": assignment_id, "user_id": current_user.id}, single=True)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    draft = _latest(db, "assignment_drafts", {"assignment_id": assignment_id, "user_id": current_user.id})
    if not draft:
        raise HTTPException(400, "Please generate a draft before creating a PDF")

    filename = f"scu_{current_user.id[:6]}_{assignment_id[:6]}.pdf"
    abs_path, file_size = build_assignment_pdf(
        course_name=assignment["course_name"], assignment_title=assignment["assignment_title"],
        solution_markdown=draft["draft_markdown"], output_filename=filename, student_info=current_user.full_name,
    )
    doc_id = str(uuid.uuid4())
    db.insert("generated_documents", {
        "id": doc_id, "user_id": current_user.id, "assignment_id": assignment_id,
        "draft_id": draft["id"], "filename": filename, "storage_path": abs_path,
        "file_size_bytes": file_size, "mime_type": "application/pdf",
    })
    db.update("assignments", {"id": assignment_id, "user_id": current_user.id}, {"current_status": "pdf_generated"})
    return DocumentResponse(id=doc_id, user_id=current_user.id, assignment_id=assignment_id,
                            filename=filename, file_size_bytes=file_size)


@router.get("/{assignment_id}/document", response_model=DocumentResponse)
def get_document_info(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    doc = _latest(get_database(), "generated_documents", {"assignment_id": assignment_id, "user_id": current_user.id})
    if not doc:
        raise HTTPException(404, "No generated document found")
    return DocumentResponse(id=doc["id"], user_id=doc["user_id"], assignment_id=doc["assignment_id"],
                            filename=doc["filename"], file_size_bytes=doc.get("file_size_bytes"),
                            created_at=doc.get("created_at"))


@router.get("/{assignment_id}/download-pdf")
def download_pdf(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    doc = _latest(get_database(), "generated_documents", {"assignment_id": assignment_id, "user_id": current_user.id})
    if not doc:
        raise HTTPException(404, "Document not found")
    file_path = get_authorized_document_path(current_user.id, doc["filename"])
    return FileResponse(path=str(file_path), media_type="application/pdf", filename=doc["filename"])

