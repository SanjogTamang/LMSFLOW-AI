import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import FileResponse
from backend.models import DocumentResponse
from backend.database import local_store
from backend.security import get_current_user, AuthenticatedUser
from backend.services.pdf_service import build_assignment_pdf
from backend.services.storage_service import get_authorized_document_path

router = APIRouter(prefix="/api/assignments", tags=["Documents & PDFs"])

@router.post("/{assignment_id}/generate-pdf", response_model=DocumentResponse)
def generate_pdf_document(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    """Compiles the approved draft into a styled ReportLab PDF."""
    with local_store.get_conn() as conn:
        assignment = conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Please generate a draft before creating a PDF.")

    filename = f"scu_{current_user.id[:6]}_{assignment_id[:6]}.pdf"
    abs_path, file_size = build_assignment_pdf(
        course_name=assignment["course_name"],
        assignment_title=assignment["assignment_title"],
        solution_markdown=draft["draft_markdown"],
        output_filename=filename,
        student_info=current_user.full_name
    )

    doc_id = str(uuid.uuid4())
    with local_store.get_conn() as conn:
        conn.execute("""
            INSERT INTO generated_documents (id, user_id, assignment_id, draft_id, filename, storage_path, file_size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (doc_id, current_user.id, assignment_id, draft["id"], filename, abs_path, file_size))
        conn.execute("UPDATE assignments SET current_status = 'pdf_generated' WHERE id = ?", (assignment_id,))
        conn.commit()

    return DocumentResponse(
        id=doc_id,
        user_id=current_user.id,
        assignment_id=assignment_id,
        filename=filename,
        file_size_bytes=file_size
    )

@router.get("/{assignment_id}/document", response_model=DocumentResponse)
def get_document_info(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    """Retrieves document record for the assignment."""
    with local_store.get_conn() as conn:
        doc = conn.execute("""
            SELECT * FROM generated_documents
            WHERE assignment_id = ? AND user_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (assignment_id, current_user.id)).fetchone()

    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No generated document found for this assignment.")

    return DocumentResponse(
        id=doc["id"],
        user_id=doc["user_id"],
        assignment_id=doc["assignment_id"],
        filename=doc["filename"],
        file_size_bytes=doc["file_size_bytes"],
        created_at=doc["created_at"]
    )

@router.get("/{assignment_id}/download-pdf")
def download_pdf(assignment_id: str, current_user: AuthenticatedUser = Depends(get_current_user)):
    """
    Downloads or previews the PDF file.
    Enforces server-side authorization: only the document owner can access it.
    """
    with local_store.get_conn() as conn:
        doc = conn.execute("""
            SELECT filename, user_id FROM generated_documents
            WHERE assignment_id = ? AND user_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (assignment_id, current_user.id)).fetchone()

    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    file_path = get_authorized_document_path(current_user.id, doc["filename"])
    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=doc["filename"]
    )

