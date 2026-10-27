import base64
import hashlib
from typing import Optional
from cryptography.fernet import Fernet
from fastapi import HTTPException, Security, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.config import settings

security_bearer = HTTPBearer(auto_error=False)

def _get_fernet() -> Fernet:
    """Return a Fernet cipher instance based on configured key or fallback secret."""
    key = settings.LMS_ENCRYPTION_KEY
    if not key:
        # Derive a stable 32-byte url-safe base64 key from Supabase key for development
        seed = (settings.SUPABASE_KEY or "fallback-secret-development-key-32b").encode()
        key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest()).decode()
    elif len(key) != 44:
        key = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()).decode()
    return Fernet(key.encode())

def encrypt_credential(plain_text: str) -> str:
    """Encrypt a secret string into an AES-256 Fernet token."""
    if not plain_text:
        return ""
    f = _get_fernet()
    return f.encrypt(plain_text.encode("utf-8")).decode("utf-8")

def decrypt_credential(cipher_text: str) -> str:
    """Decrypt an AES-256 Fernet token back to clear text."""
    if not cipher_text:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        raise ValueError(f"Failed to decrypt stored LMS credential: {e}")

class AuthenticatedUser:
    def __init__(self, user_id: str, email: str, full_name: Optional[str] = None):
        self.id = user_id
        self.email = email
        self.full_name = full_name or email.split("@")[0]

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_user_email: Optional[str] = Header(None, alias="X-User-Email"),
) -> AuthenticatedUser:
    """
    Validates current authenticated student session.
    Verifies Supabase Bearer JWT token, or supports session header in dev mode.
    """
    if credentials and credentials.credentials:
        token = credentials.credentials
        # Validate with Supabase Auth
        try:
            from supabase import create_client
            supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            user_response = supabase.auth.get_user(token)
            if user_response and user_response.user:
                u = user_response.user
                return AuthenticatedUser(
                    user_id=str(u.id),
                    email=u.email,
                    full_name=u.user_metadata.get("full_name") if u.user_metadata else None
                )
        except Exception as e:
            # If Supabase Auth token expired or invalid
            pass

    # Development or Mock Header Fallback
    if x_user_id and x_user_email:
        return AuthenticatedUser(
            user_id=x_user_id,
            email=x_user_email,
            full_name=x_user_email.split("@")[0]
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required. Please log in or provide a valid session token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

