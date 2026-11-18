
import hashlib
import secrets
import threading
from datetime import datetime, timedelta, timezone

from backend.security import encrypt_credential, decrypt_credential

# Guest sessions expire after 2 hours.
SESSION_DURATION = timedelta(hours=2)

# Temporary in-memory session storage.
_sessions = {}
_lock = threading.Lock()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def cleanup_expired_sessions():
    """Remove expired guest sessions."""
    now = datetime.now(timezone.utc)

    with _lock:
        expired = [
            key for key, session in _sessions.items()
            if session["expires_at"] <= now
        ]

        for key in expired:
            del _sessions[key]


def create_guest_session(lms_student_id: str, lms_password: str) -> dict:
    """Create a temporary guest session with encrypted LMS credentials."""
    if not lms_student_id or not lms_password:
        raise ValueError("LMS student ID and password are required.")

    cleanup_expired_sessions()

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + SESSION_DURATION

    session = {
        "lms_student_id": lms_student_id,
        "encrypted_lms_password": encrypt_credential(lms_password),
        "expires_at": expires_at,
    }

    with _lock:
        _sessions[_token_hash(token)] = session

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
    }


def get_guest_session(token: str) -> dict:
    """Retrieve valid guest session and decrypt credentials for internal use."""
    if not token:
        raise ValueError("Guest session token is required.")

    key = _token_hash(token)

    with _lock:
        session = _sessions.get(key)

        if not session:
            raise ValueError("Guest session not found or expired.")

        if session["expires_at"] <= datetime.now(timezone.utc):
            del _sessions[key]
            raise ValueError("Guest session has expired.")

        return {
            "lms_student_id": session["lms_student_id"],
            "lms_password": decrypt_credential(
                session["encrypted_lms_password"]
            ),
            "expires_at": session["expires_at"].isoformat(),
        }


def delete_guest_session(token: str) -> bool:
    """Delete a guest session and its encrypted credentials."""
    if not token:
        return False

    with _lock:
        return _sessions.pop(_token_hash(token), None) is not None
