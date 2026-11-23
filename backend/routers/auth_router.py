import os

frontend_url = os.getenv("FRONTEND_URL", "http://127.0.0.1:8000")
from fastapi import APIRouter, Depends, HTTPException, status

from backend.database import get_database, get_supabase_client
from backend.models import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    UserProfileResponse,
)
from backend.security import AuthenticatedUser, get_current_user

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def _profile_response(profile: dict) -> UserProfileResponse:
    return UserProfileResponse(
        id=str(profile["id"]),
        scu_student_id=profile.get("scu_student_id"),
        email=profile.get("email"),
        full_name=profile.get("full_name") or profile.get("email") or "Student",
        is_scu_verified=bool(profile.get("is_scu_verified", False)),
        created_at=profile.get("created_at"),
    )


def _auth_error(exc: Exception) -> HTTPException:
    error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid email or password.",
    )
    error.__cause__ = exc
    return error


def _get_or_create_profile(user, email: str, full_name: str) -> dict:
    """
    Find the profile belonging to this Supabase Auth user.
    Never overwrite a different user's profile just because the email matches.
    """
    db = get_database()
    user_id = str(user.id)

    profile = db.select(
        "profiles",
        {"id": user_id},
        single=True,
    )

    if profile:
        return profile

    email_profile = db.select(
        "profiles",
        {"email": email},
        single=True,
    )

    if email_profile:
        if str(email_profile["id"]) != user_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This email is already linked to an existing platform profile. "
                    "Please try logging in or contact support."
                ),
            )
        return email_profile

    profile_values = {
        "id": user_id,
        "email": email,
        "full_name": full_name or "Student",
        "scu_student_id": None,
        "is_scu_verified": False,
    }

    return db.upsert("profiles", profile_values)


@router.post("/register", response_model=AuthResponse)
def register_student(req: RegisterRequest):
    email = str(req.email).strip().lower()
    full_name = req.full_name.strip()

    auth = get_supabase_client()
    if auth is None:
        raise HTTPException(
            status_code=503,
            detail="Supabase Auth is not configured.",
        )

    try:
    
        result = auth.auth.sign_up({
            "email": email,
            "password": req.password,
            "options": {
                "data": {
                    "full_name": full_name,
                },
                "email_redirect_to":frontend_url,
            },
        })
    except Exception as exc:
        print(f"SUPABASE REGISTRATION ERROR: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=400,
            detail=400,
        ) from exc

    user = result.user
    if not user:
        raise HTTPException(
            status_code=400,
            detail="Supabase did not create the user account.",
        )

    profile = _get_or_create_profile(
        user=user,
        email=email,
        full_name=full_name,
    )

    session = result.session

    if not session:
        return AuthResponse(
            token="",
            user=_profile_response(profile),
            message=(
                "Registration successful. Please check your email to confirm "
                "your account, then log in."
            ),
        )

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
        raise HTTPException(
            status_code=503,
            detail="Supabase Auth is not configured.",
        )

    # New accounts log in using email.
    # Legacy accounts may still use their SCU student ID.
    if "@" in login_id:
        email = login_id.lower()
    else:
        profiles = get_database().select(
            "profiles",
            {"scu_student_id": login_id},
            columns="email, full_name, scu_student_id, id, is_scu_verified",
        )

        if not profiles or not profiles[0].get("email"):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password.",
            )

        email = profiles[0]["email"].lower()
    print("LOGIN ATTEMPT:", email)
    try:
        result = auth.auth.sign_in_with_password({
            "email": email,
            "password": req.password,
        })
    except Exception as exc:
        print("LOGIN ERROR:", type(exc).__name__, str(exc))
        raise _auth_error(exc)

    if not result.user or not result.session:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password.",
        )

    profile = _get_or_create_profile(
        user=result.user,
        email=result.user.email or email,
        full_name=(
            (result.user.user_metadata or {}).get("full_name")
            or email.split("@")[0]
        ),
    )

    return AuthResponse(
        token=result.session.access_token,
        user=_profile_response(profile),
        message="Authenticated with Supabase Auth.",
    )


@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    profile = get_database().select(
        "profiles",
        {"id": current_user.id},
        single=True,
    )

    if not profile:
        raise HTTPException(
            status_code=404,
            detail="Profile not found.",
        )

    return _profile_response(profile)
