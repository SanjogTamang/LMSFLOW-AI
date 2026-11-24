
import uuid
from typing import Optional, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from backend.database import get_database
from backend.security import (
    AuthenticatedUser,
    decrypt_credential,
    get_current_user,
)
from backend.services.session_service import get_guest_session
from backend.services.gemini_service import (
    generate_assignment_solution,
    chat_with_assignment,
)
from backend.services.pdf_service import build_assignment_pdf
from backend.services.playwright_lms import (
    perform_lms_submission,
    discover_student_assignments,
)


router = APIRouter(
    prefix="/api/workflow",
    tags=["Automatic Assignment Workflow"],
)


# REQUEST MODELS

class GenerateRequest(BaseModel):
    course_name: str = Field(..., min_length=1)
    assignment_title: str = Field(..., min_length=1)
    instructions: str = ""
    custom_instructions: str = ""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    course_name: str = Field(..., min_length=1)
    assignment_title: str = Field(..., min_length=1)
    instructions: str = ""
    messages: list[ChatMessage] = Field(default_factory=list)

class SubmitRequest(GenerateRequest):
      assignment_id: Optional[str] = None
      solution_markdown: Optional[str] = None
      assignment_url: str = Field(..., min_length=1)

      submission_type: Literal["F", "T", "FT"] = "F"
      text_content: Optional[str] = None

      student_approved: bool = False
      safe_test_mode: bool = True


# SHARED CHAT FUNCTION

def _chat(req: ChatRequest):
    reply, model_name = chat_with_assignment(
        course_name=req.course_name,
        assignment_title=req.assignment_title,
        instructions=req.instructions,
        messages=[
            message.model_dump()
            for message in req.messages
        ],
    )

    return {
        "success": True,
        "reply": reply,
        "model_used": model_name,
    }


# SHARED GENERATION FUNCTION

def _generate(req: GenerateRequest):
    answer, model_name = generate_assignment_solution(
        course_name=req.course_name,
        assignment_title=req.assignment_title,
        instructions=req.instructions,
        student_notes=req.custom_instructions,
    )

    return {
        "success": True,
        "course_name": req.course_name,
        "assignment_title": req.assignment_title,
        "answer": answer,
        "model_used": model_name,
        "requires_student_review": True,
    }


#

# REGISTERED STUDENT CREDENTIALS

def _registered_credentials(user: AuthenticatedUser):
    db = get_database()

    connection = db.select(
        "student_lms_connections",
        {
            "user_id": user.id,
            "connection_status": "connected",
        },
        single=True,
    )

    if not connection:
        raise HTTPException(
            status_code=400,
            detail="Connect your SCU LMS account first.",
        )

    try:
        password = decrypt_credential(
            connection["encrypted_lms_password"]
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not decrypt your saved LMS credentials.",
        ) from exc

    return (
        connection["lms_student_id"],
        password,
        user.full_name,
    )



@router.post("/submit")
def submit_registered(
    req: SubmitRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    student_id, password, student_name = _registered_credentials(user)
 
    

    return _submit(
        req=req,
        student_id=student_id,
        password=password,
        student_name=student_name,
    )



# GUEST STUDENT CREDENTIALS

def _guest_credentials(authorization: Optional[str]):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Guest session token required.",
        )

    token = authorization.split(" ", 1)[1]

    try:
        session = get_guest_session(token)

        return (
            session["lms_student_id"],
            session["lms_password"],
            "SCU Student",
        )

    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail="Guest session is invalid or expired.",
        ) from exc


# REGISTERED STUDENTS

@router.get("/assignments")
def scan_registered_assignments(
    user: AuthenticatedUser = Depends(get_current_user),
):
    student_id, password, _ = _registered_credentials(user)

    try:
        assignments = discover_student_assignments(
            student_id,
            password,
            headless=True,
        )

        return {
            "total": len(assignments),
            "assignments": assignments,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not scan SCU LMS: {exc}",
        ) from exc


@router.post("/chat")
def chat_registered(
    req: ChatRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        return _chat(req)

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini chat failed: {exc}",
        ) from exc


@router.post("/generate")
def generate_registered(
    req: GenerateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    try:
        return _generate(req)

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini generation failed: {exc}",
        ) from exc


def _submit(
    req: SubmitRequest,
    student_id: str,
    password: str,
    student_name: str,
):
    """Shared submission implementation for registered and guest students."""
    if not req.student_approved:
        raise HTTPException(
            status_code=400,
            detail="Please review and approve the generated answer first.",
        )

    submission_type = req.submission_type

    if submission_type in ("F", "FT") and not req.solution_markdown:
        raise HTTPException(
            status_code=400,
            detail="Assignment solution is required for PDF generation.",
        )

    if submission_type in ("T", "FT") and not req.text_content:
        raise HTTPException(
            status_code=400,
            detail="Text content is required for this submission format.",
        )

    pdf_path = None
    file_size = 0

    try:
        if submission_type in ("F", "FT"):
            filename = f"scu_assignment_{uuid.uuid4().hex}.pdf"
            pdf_path, file_size = build_assignment_pdf(
                course_name=req.course_name,
                assignment_title=req.assignment_title,
                solution_markdown=req.solution_markdown,
                output_filename=filename,
                student_info=student_name,
            )

        success, evidence_path, message = perform_lms_submission(
            lms_student_id=student_id,
            lms_password=password,
            course_name=req.course_name,
            assignment_title=req.assignment_title,
            pdf_path=str(pdf_path) if pdf_path else None,
            safe_test_mode=req.safe_test_mode,
            headless=True,
            assignment_url=req.assignment_url,
            student_approved=req.student_approved,
            submission_type=submission_type,
            text_content=req.text_content,
        )

        return {
            "success": success,
            "message": message,
            "submission_type": submission_type,
            "file_size_bytes": file_size,
            "safe_test_mode": req.safe_test_mode,
            "evidence_available": bool(evidence_path),
            "next_step": (
                "Review the LMS result before proceeding."
                if req.safe_test_mode or not success
                else "Check the submission status in SCU LMS."
            ),
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Assignment workflow failed: {exc}",
        ) from exc


# GUEST STUDENTS

@router.post("/guest/chat")
def chat_guest(
    req: ChatRequest,
    authorization: Optional[str] = Header(default=None),
):
    _guest_credentials(authorization)

    try:
        return _chat(req)

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini chat failed: {exc}",
        ) from exc


@router.post("/guest/generate")
def generate_guest(
    req: GenerateRequest,
    authorization: Optional[str] = Header(default=None),
):
    _guest_credentials(authorization)

    try:
        return _generate(req)

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini generation failed: {exc}",
        ) from exc


@router.post("/guest/submit")
def submit_guest(
    req: SubmitRequest,
    authorization: Optional[str] = Header(default=None),
):
    student_id, password, student_name = _guest_credentials(
        authorization
    )

    return _submit(
        req,
        student_id,
        password,
        student_name,
    )
