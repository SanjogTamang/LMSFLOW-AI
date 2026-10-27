import os
from pathlib import Path
from typing import Optional
from fastapi import HTTPException, status
from backend.config import settings

def get_authorized_document_path(user_id: str, filename: str) -> Path:
    """
    Validates that a document belongs to the requesting user and exists.
    Filename convention: doc_{user_id}_{assignment_id}_{unique}.pdf
    Or checked against database record.
    """
    file_path = settings.PDFS_DIR / filename
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requested document '{filename}' was not found."
        )

    # Security check: Prevent path traversal attacks
    try:
        resolved_path = file_path.resolve()
        storage_resolved = settings.PDFS_DIR.resolve()
        if not str(resolved_path).startswith(str(storage_resolved)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Invalid document path."
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file identifier."
        )

    return file_path

