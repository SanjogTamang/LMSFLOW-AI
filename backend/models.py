from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field

# ── User & Auth Models ────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    student_id: str = Field(..., min_length=4, description="SCU Student ID number, e.g. 20240301001")
    password: str = Field(..., min_length=4)
    full_name: str
    email: Optional[str] = None

class LoginRequest(BaseModel):
    student_id: str = Field(..., description="SCU Student ID number (e.g. 20240301001) or Email")
    password: str

class UserProfileResponse(BaseModel):
    id: str
    scu_student_id: str
    email: Optional[str] = None
    full_name: str
    is_scu_verified: bool = False
    created_at: Optional[str] = None

class AuthResponse(BaseModel):
    token: str
    user: UserProfileResponse
    message: str

# ── LMS Connection Models ────────────────────────────────────────────────────
class ConnectLMSRequest(BaseModel):
    lms_student_id: str
    lms_password: str

class LMSConnectionResponse(BaseModel):
    user_id: str
    lms_student_id: str
    connection_status: str  # 'connected', 'disconnected', 'failed', 'requires_mfa'
    last_verified_at: Optional[str] = None
    last_error_message: Optional[str] = None

# ── Assignment & Course Models ───────────────────────────────────────────────
class AssignmentCreateRequest(BaseModel):
    course_name: str
    assignment_title: str
    instructions: Optional[str] = ""
    due_date: Optional[str] = None
    submission_format: Optional[str] = "pdf"
    lms_assignment_url: Optional[str] = None

class AssignmentResponse(BaseModel):
    id: str
    user_id: str
    course_name: str
    assignment_title: str
    instructions: Optional[str] = ""
    due_date: Optional[str] = None
    submission_format: str = "pdf"
    current_status: str
    created_at: Optional[str] = None

# ── Draft & AI Models ────────────────────────────────────────────────────────
class GenerateDraftRequest(BaseModel):
    custom_instructions: Optional[str] = None

class UpdateDraftRequest(BaseModel):
    draft_title: Optional[str] = None
    draft_markdown: str

class DraftResponse(BaseModel):
    id: str
    user_id: str
    assignment_id: str
    model_used: str
    draft_title: Optional[str] = None
    draft_markdown: str
    is_student_approved: bool = False
    approved_at: Optional[str] = None
    created_at: Optional[str] = None

# ── Document & PDF Models ────────────────────────────────────────────────────
class DocumentResponse(BaseModel):
    id: str
    user_id: str
    assignment_id: str
    filename: str
    file_size_bytes: Optional[int] = 0
    created_at: Optional[str] = None

# ── Job & Audit Models ───────────────────────────────────────────────────────
class JobResponse(BaseModel):
    id: str
    user_id: str
    assignment_id: str
    job_type: str
    status: str
    progress_percentage: int
    current_step: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None

class SubmissionApprovalRequest(BaseModel):
    confirm_submission: bool = True

