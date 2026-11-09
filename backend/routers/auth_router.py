from fastapi import APIRouter, Depends, HTTPException, status

from backend.database import get_database, get_supabase_client
from backend.models import AuthResponse, LoginRequest, RegisterRequest, UserProfileResponse
from backend.security import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def _profile_response(profile: dict) -> UserProfileResponse:
    return UserProfileResponse(
        id=str(profile["id"]),
        scu_student_id=profile.get("scu_student_id") or str(profile["id"]),
        email=profile.get("email"),
        full_name=profile.get("full_name") or profile.get("email", "Student"),
        is_scu_verified=bool(profile.get("is_scu_verified", False)),
        created_at=profile.get("created_at"),
    )


def _auth_error(exc: Exception) -> HTTPException:
    error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Supabase authentication failed.",
    )
    error.__cause__ = exc
    return error


@router.post("/register", response_model=AuthResponse)
def register_student(req: RegisterRequest):
    student_id = req.student_id.strip()
    student_email = (req.email or f"{student_id}@scu.ac.kr").strip().lower()
    auth = get_supabase_client()
    if auth is None:
        raise HTTPException(status_code=503, detail="Supabase Auth is not configured")

    try:
        result = auth.auth.sign_up({
            "email": student_email,
            "password": req.password,
            "options": {"data": {"full_name": req.full_name, "scu_student_id": student_id}},
        })
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not register this account") from exc

    user = result.user
    session = result.session
    if not user or not session:
        raise HTTPException(
            status_code=409,
            detail="Registration needs email confirmation before password sign-in is available.",
        )

    profile = get_database().upsert("profiles", {
        "id": str(user.id),
        "email": user.email or student_email,
        "full_name": req.full_name,
        "scu_student_id": student_id,
        "is_scu_verified": False,
    })
    return AuthResponse(
        token=session.access_token,
        user=_profile_response(profile),
        message="Student account registered successfully.",
    )


@router.post("/login", response_model=AuthResponse)
def login_student(req: LoginRequest):
    login_id = req.student_id.strip()
    auth = get_supabase_client()
    if auth is None:
        raise HTTPException(status_code=503, detail="Supabase Auth is not configured")

    email = login_id
    if "@" not in login_id:
        profiles = get_database().select(
            "profiles", {"scu_student_id": login_id}, columns="email, full_name, scu_student_id, id, is_scu_verified"
        )
        if not profiles:
            raise HTTPException(status_code=401, detail="Invalid student ID or password")
        email = profiles[0]["email"]

    try:
        result = auth.auth.sign_in_with_password({"email": email, "password": req.password})
    except Exception as exc:
        raise _auth_error(exc)
    if not result.user or not result.session:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    profile = get_database().select("profiles", {"id": str(result.user.id)}, single=True)
    if not profile:
        raise HTTPException(status_code=404, detail="Authenticated profile is missing")
    return AuthResponse(
        token=result.session.access_token,
        user=_profile_response(profile),
        message="Authenticated with Supabase Auth.",
    )


@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(current_user: AuthenticatedUser = Depends(get_current_user)):
    profile = get_database().select("profiles", {"id": current_user.id}, single=True)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return _profile_response(profile)
