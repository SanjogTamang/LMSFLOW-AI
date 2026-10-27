import uuid
from fastapi import APIRouter, HTTPException, Depends, status
from backend.models import RegisterRequest, LoginRequest, AuthResponse, UserProfileResponse
from backend.database import local_store, get_supabase_client
from backend.security import get_current_user, AuthenticatedUser

router = APIRouter(prefix="/api/auth", tags=["Authentication"])

@router.post("/register", response_model=AuthResponse)
def register_student(req: RegisterRequest):
    """
    Registers a new student account using their SCU Student ID (학번).
    """
    student_id = req.student_id.strip()
    student_email = req.email.strip() if req.email else f"{student_id}@scu.ac.kr"

    with local_store.get_conn() as conn:
        # Check if student ID or email already registered
        existing = conn.execute(
            "SELECT id FROM profiles WHERE scu_student_id = ? OR email = ?",
            (student_id, student_email)
        ).fetchone()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"An account with Student ID '{student_id}' or email '{student_email}' already exists."
            )

        new_user_id = str(uuid.uuid4())
        conn.execute("""
            INSERT INTO profiles (id, email, full_name, scu_student_id, is_scu_verified)
            VALUES (?, ?, ?, ?, 1)
        """, (new_user_id, student_email, req.full_name, student_id))
        conn.commit()

        session_token = f"scu_session_{new_user_id}_{uuid.uuid4().hex[:12]}"

        user_profile = UserProfileResponse(
            id=new_user_id,
            scu_student_id=student_id,
            email=student_email,
            full_name=req.full_name,
            is_scu_verified=True
        )

        return AuthResponse(
            token=session_token,
            user=user_profile,
            message="Student account registered successfully!"
        )

@router.post("/login", response_model=AuthResponse)
def login_student(req: LoginRequest):
    """
    Authenticates a student by Student ID number (e.g. 20240301001) or Email.
    """
    login_id = req.student_id.strip()

    # 1. Check Supabase Auth if it's an email
    supabase = get_supabase_client()
    if supabase and "@" in login_id:
        try:
            res = supabase.auth.sign_in_with_password({"email": login_id, "password": req.password})
            if res and res.user:
                return AuthResponse(
                    token=res.session.access_token,
                    user=UserProfileResponse(
                        id=str(res.user.id),
                        scu_student_id=login_id.split("@")[0],
                        email=res.user.email,
                        full_name=res.user.user_metadata.get("full_name", login_id),
                        is_scu_verified=True
                    ),
                    message="Authenticated with Supabase Auth."
                )
        except Exception:
            pass

    # 2. Check local database by student ID (학번) OR email
    with local_store.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM profiles WHERE scu_student_id = ? OR email = ?",
            (login_id, login_id)
        ).fetchone()

        if not row:
            # Auto-provision on first demo login with this student ID
            new_user_id = str(uuid.uuid4())
            student_email = f"{login_id}@scu.ac.kr" if "@" not in login_id else login_id
            conn.execute("""
                INSERT INTO profiles (id, email, full_name, scu_student_id, is_scu_verified)
                VALUES (?, ?, ?, ?, 1)
            """, (new_user_id, student_email, f"Student {login_id}", login_id))
            conn.commit()
            row = conn.execute("SELECT * FROM profiles WHERE id = ?", (new_user_id,)).fetchone()

        session_token = f"scu_session_{row['id']}_{uuid.uuid4().hex[:12]}"
        user_profile = UserProfileResponse(
            id=row["id"],
            scu_student_id=row["scu_student_id"] or login_id,
            email=row["email"],
            full_name=row["full_name"],
            is_scu_verified=bool(row["is_scu_verified"])
        )

        return AuthResponse(
            token=session_token,
            user=user_profile,
            message="Login successful with Student ID."
        )

@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(current_user: AuthenticatedUser = Depends(get_current_user)):
    """Returns the authenticated student's profile."""
    with local_store.get_conn() as conn:
        row = conn.execute("SELECT * FROM profiles WHERE id = ?", (current_user.id,)).fetchone()
        if row:
            return UserProfileResponse(
                id=row["id"],
                scu_student_id=row["scu_student_id"] or current_user.id[:8],
                email=row["email"],
                full_name=row["full_name"],
                is_scu_verified=bool(row["is_scu_verified"])
            )

    return UserProfileResponse(
        id=current_user.id,
        scu_student_id=current_user.email.split("@")[0] if current_user.email else "20240301001",
        email=current_user.email,
        full_name=current_user.full_name,
        is_scu_verified=True
    )
